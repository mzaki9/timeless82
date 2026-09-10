using System;
using System.Threading.Tasks;
using Windows.Media.Control;

class Program
{
    static async Task<int> Main()
    {
        var mgr = await GlobalSystemMediaTransportControlsSessionManager.RequestAsync();
        var s = mgr.GetCurrentSession();
        if (s == null) { Console.WriteLine("NO-SESSION"); return 0; }
        var status = s.GetPlaybackInfo().PlaybackStatus.ToString();
        var p = await s.TryGetMediaPropertiesAsync();
        Console.WriteLine(status + "\t" + p.Title + "\t" + p.Artist);
        return 0;
    }
}
