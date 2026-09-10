using System;
using System.Diagnostics;
using System.Threading.Tasks;
using Windows.Media.Control;

class Program
{
    // Hard cap: the WinRT SMTC broker call can hang indefinitely (thread
    // parked in an out-of-process LPC reply) when a media session app or the
    // broker is unresponsive. Never let that wedge the caller: run the work
    // on a background thread and give up after a few seconds, printing the
    // same "NO-SESSION" sentinel so nowlive keeps its cadence.
    const int TimeoutMs = 4000;

    static async Task<int> Main()
    {
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
}
