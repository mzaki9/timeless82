using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using Windows.Media.Control;
using Windows.Storage.Streams;

class Program
{
    // Hard cap: the WinRT SMTC broker call can hang indefinitely (thread
    // parked in an out-of-process LPC reply) when a media session app or the
    // broker is unresponsive. Never let that wedge the caller: run the work
    // on a background thread and give up after a few seconds, printing the
    // same "NO-SESSION" sentinel so nowlive keeps its cadence.
    const int TimeoutMs = 4000;

    // Usage: nowplaying.exe [art-output-path]. The path is best-effort: the
    // raw SMTC thumbnail bytes (PNG/JPEG) are written there when the session
    // has cover art, and failures only go to stderr so the TSV line is never
    // held back.
    static async Task<int> Main(string[] args)
    {
        string artPath = args.Length > 0 ? args[0] : null;
        var sw = Stopwatch.StartNew();
        var work = Task.Run(async () =>
        {
            Console.Error.WriteLine($"stage: request ({sw.ElapsedMilliseconds}ms)");
            var mgr = await GlobalSystemMediaTransportControlsSessionManager.RequestAsync();
            Console.Error.WriteLine($"stage: manager ({sw.ElapsedMilliseconds}ms)");
            var s = mgr.GetCurrentSession();
            if (s == null) { Console.WriteLine("NO-SESSION"); return; }
            var status = s.GetPlaybackInfo().PlaybackStatus.ToString();
            Console.Error.WriteLine($"stage: playbackinfo ({sw.ElapsedMilliseconds}ms)");
            var p = await s.TryGetMediaPropertiesAsync();
            Console.Error.WriteLine($"stage: props ({sw.ElapsedMilliseconds}ms)");
            if (artPath != null)
            {
                try
                {
                    if (await DumpArt(p, artPath))
                        Console.Error.WriteLine($"stage: art ({sw.ElapsedMilliseconds}ms)");
                }
                catch (Exception e)
                {
                    Console.Error.WriteLine("art: " + e.Message);
                }
            }
            Console.WriteLine(status + "\t" + p.Title + "\t" + p.Artist);
        });
        var done = await Task.WhenAny(work, Task.Delay(TimeoutMs));
        if (done != work)
        {
            Console.Error.WriteLine($"stage: TIMEOUT>{TimeoutMs}ms, giving up");
            Console.WriteLine("NO-SESSION");
            return 0;
        }
        try { await work; }
        catch (Exception e)
        {
            Console.Error.WriteLine("stage: error " + e.Message);
            Console.WriteLine("NO-SESSION");
        }
        return 0;
    }

    // Returns false when the session carries no thumbnail. The target is
    // deleted first so a track without cover art never keeps the previous
    // track's image (the file's existence is what nowart.load trusts).
    static async Task<bool> DumpArt(
        GlobalSystemMediaTransportControlsSessionMediaProperties p, string path)
    {
        var thumb = p.Thumbnail;
        if (thumb == null)
        {
            Console.Error.WriteLine("art: no thumbnail");
            File.Delete(path);
            return false;
        }
        using var ras = await thumb.OpenReadAsync();
        using var reader = new DataReader(ras);
        using var ms = new MemoryStream();
        uint loaded;
        while ((loaded = await reader.LoadAsync(65536)) > 0)
        {
            var chunk = new byte[loaded];
            reader.ReadBytes(chunk);
            ms.Write(chunk, 0, chunk.Length);
        }
        if (ms.Length == 0)
        {
            Console.Error.WriteLine("art: empty stream");
            File.Delete(path);
            return false;
        }
        File.WriteAllBytes(path, ms.ToArray());
        return true;
    }
}
