// timeless82.exe — Windows CLI, zero-dep (hid.dll + setupapi only).
// v0.1: list + caps. Zero HID writes: opens GENERIC_READ, queries caps only.
// Target: VID 320F PID 5055, LED channel MI_01 Col04 usage FF1C:0092 (64/64).
// Never touches OTA channel MI_02 FFEF for writes (caps query is read-only).
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

// MinGW may miss these with plain includes; declare explicitly.
extern void __stdcall HidD_GetHidGuid(LPGUID HidGuid);

typedef struct {
    char  path[512];
    USHORT vid, pid;
    USHORT usage, usagePage;
    USHORT inLen, outLen, featLen;
    char  manuf[128], prod[128];
    int   opened; // 1 if we could open GENERIC_READ
} DevInfo;

static void wstr_to_utf8(const wchar_t *w, char *out, int outsz) {
    if (!w || !out || outsz <= 0) return;
    WideCharToMultiByte(CP_UTF8, 0, w, -1, out, outsz, NULL, NULL);
    out[outsz - 1] = 0;
}

static int is_target(USHORT vid, USHORT pid) {
    return vid == 0x320F && pid == 0x5055;
}

// Enumerate present HID interfaces, open GENERIC_READ, get attrs+caps+strings.
static int enumerate(DevInfo *devs, int maxdevs, int targetOnly) {
    GUID guid;
    HidD_GetHidGuid(&guid);
    HDEVINFO set = SetupDiGetClassDevsA(&guid, NULL, NULL,
                                        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (set == INVALID_HANDLE_VALUE) {
        printf("ERR SetupDiGetClassDevs: %lu\n", GetLastError());
        return -1;
    }
    int n = 0;
    DWORD idx = 0;
    SP_DEVICE_INTERFACE_DATA ifd;
    ifd.cbSize = sizeof(ifd);
    while (SetupDiEnumDeviceInterfaces(set, NULL, &guid, idx, &ifd)) {
        idx++;
        DWORD need = 0;
        SetupDiGetDeviceInterfaceDetailA(set, &ifd, NULL, 0, &need, NULL);
        if (GetLastError() != ERROR_INSUFFICIENT_BUFFER || need < sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_A) + 2)
            continue;
        char *buf = (char *)HeapAlloc(GetProcessHeap(), 0, need + 2);
        if (!buf) continue;
        SP_DEVICE_INTERFACE_DETAIL_DATA_A *det = (SP_DEVICE_INTERFACE_DETAIL_DATA_A *)buf;
        det->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_A);
        if (!SetupDiGetDeviceInterfaceDetailA(set, &ifd, det, need, NULL, NULL)) {
            HeapFree(GetProcessHeap(), 0, buf);
            continue;
        }
        HANDLE h = CreateFileA(det->DevicePath, GENERIC_READ,
                               FILE_SHARE_READ | FILE_SHARE_WRITE,
                               NULL, OPEN_EXISTING, 0, NULL);
        if (h == INVALID_HANDLE_VALUE) {
            // Exclusive (keyboard/mouse) — record path only if it looks like HID.
            HeapFree(GetProcessHeap(), 0, buf);
            continue;
        }
        HIDD_ATTRIBUTES attr;
        attr.Size = sizeof(attr);
        USHORT vid = 0, pid = 0;
        if (HidD_GetAttributes(h, &attr)) { vid = attr.VendorID; pid = attr.ProductID; }
        if (targetOnly && !is_target(vid, pid)) { CloseHandle(h); HeapFree(GetProcessHeap(), 0, buf); continue; }
        if (n < maxdevs) {
            DevInfo *d = &devs[n];
            memset(d, 0, sizeof(*d));
            strncpy(d->path, det->DevicePath, sizeof(d->path) - 1);
            d->vid = vid; d->pid = pid; d->opened = 1;
            PHIDP_PREPARSED_DATA pp = NULL;
            if (HidD_GetPreparsedData(h, &pp) && pp) {
                HIDP_CAPS caps;
                if (HidP_GetCaps(pp, &caps) == HIDP_STATUS_SUCCESS) {
                    d->usage = caps.Usage; d->usagePage = caps.UsagePage;
                    d->inLen = caps.InputReportByteLength;
                    d->outLen = caps.OutputReportByteLength;
                    d->featLen = caps.FeatureReportByteLength;
                }
                HidD_FreePreparsedData(pp);
            }
            wchar_t w[128];
            if (HidD_GetManufacturerString(h, w, sizeof(w))) wstr_to_utf8(w, d->manuf, sizeof(d->manuf));
            if (HidD_GetProductString(h, w, sizeof(w))) wstr_to_utf8(w, d->prod, sizeof(d->prod));
            n++;
        }
        CloseHandle(h);
        HeapFree(GetProcessHeap(), 0, buf);
    }
    SetupDiDestroyDeviceInfoList(set);
    return n;
}

static const char *tag_for(const DevInfo *d) {
    if (d->usagePage == 0xFF1C && d->usage == 0x92) return "LED-CHANNEL";
    if (d->usagePage == 0xFFEF) return "OTA-DO-NOT-WRITE";
    if (d->inLen == 33 && d->outLen == 33) return "VIA?";
    if (d->usagePage == 0x01 && d->usage == 0x06) return "keyboard";
    if (d->usagePage == 0x01 && d->usage == 0x02) return "mouse";
    if (d->usagePage == 0x0C) return "consumer";
    return "-";
}

static int cmd_list(void) {
    DevInfo devs[64];
    int n = enumerate(devs, 64, 1);
    if (n < 0) return 1;
    printf("320F:5055 HID interfaces: %d\n", n);
    for (int i = 0; i < n; i++) {
        const DevInfo *d = &devs[i];
        printf("[%d] up=%04X u=%04X in=%u out=%u feat=%u tag=%s\n"
               "    prod='%s' manuf='%s'\n"
               "    %s\n",
               i, d->usagePage, d->usage, d->inLen, d->outLen, d->featLen,
               tag_for(d), d->prod, d->manuf, d->path);
    }
    if (n == 0)
        printf("HINT: keyboard not in wired mode? Plug USB cable, close stock app if it holds the handle.\n");
    return 0;
}

static int cmd_caps(void) {
    DevInfo devs[64];
    int n = enumerate(devs, 64, 1);
    if (n < 0) return 1;
    int led = 0, ota = 0;
    for (int i = 0; i < n; i++) {
        if (devs[i].usagePage == 0xFF1C && devs[i].usage == 0x92) led++;
        if (devs[i].usagePage == 0xFFEF) ota++;
    }
    printf("interfaces=%d led_ff1c92=%d ota_ffef=%d\n", n, led, ota);
    for (int i = 0; i < n; i++) {
        const DevInfo *d = &devs[i];
        printf("[%d] %04X:%04X up=%04X u=%04X in=%d out=%d feat=%d %s\n",
               i, d->vid, d->pid, d->usagePage, d->usage,
               d->inLen, d->outLen, d->featLen, tag_for(d));
    }
    printf(led == 1 ? "OK led channel present, 64/64 expected\n"
                    : "WARN led channel count != 1, check wired mode\n");
    (void)ota;
    return 0;
}

// Open first 320F:5055 interface matching usage page/usage, with write access.
// Returns INVALID_HANDLE_VALUE on failure. Never opens FFEF (OTA) for writes:
// callers must pass explicit non-OTA usage; this helper refuses FFEF outright.
static HANDLE open_hid(USHORT wantUp, USHORT wantU, char *pathOut, int pathSz) {
    if (wantUp == 0xFFEF) { printf("REFUSED: FFEF is the OTA channel\n"); return INVALID_HANDLE_VALUE; }
    GUID guid;
    HidD_GetHidGuid(&guid);
    HDEVINFO set = SetupDiGetClassDevsA(&guid, NULL, NULL,
                                        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (set == INVALID_HANDLE_VALUE) return INVALID_HANDLE_VALUE;
    HANDLE found = INVALID_HANDLE_VALUE;
    DWORD idx = 0;
    SP_DEVICE_INTERFACE_DATA ifd;
    ifd.cbSize = sizeof(ifd);
    while (SetupDiEnumDeviceInterfaces(set, NULL, &guid, idx, &ifd)) {
        idx++;
        DWORD need = 0;
        SetupDiGetDeviceInterfaceDetailA(set, &ifd, NULL, 0, &need, NULL);
        if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) continue;
        char *buf = (char *)HeapAlloc(GetProcessHeap(), 0, need + 2);
        if (!buf) continue;
        SP_DEVICE_INTERFACE_DETAIL_DATA_A *det = (SP_DEVICE_INTERFACE_DETAIL_DATA_A *)buf;
        det->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_A);
        HANDLE h = INVALID_HANDLE_VALUE;
        if (SetupDiGetDeviceInterfaceDetailA(set, &ifd, det, need, NULL, NULL)) {
            h = CreateFileA(det->DevicePath, GENERIC_READ | GENERIC_WRITE,
                            FILE_SHARE_READ | FILE_SHARE_WRITE,
                            NULL, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, NULL);
            if (h != INVALID_HANDLE_VALUE) {
                HIDD_ATTRIBUTES attr; attr.Size = sizeof(attr);
                USHORT vid = 0, pid = 0;
                if (HidD_GetAttributes(h, &attr)) { vid = attr.VendorID; pid = attr.ProductID; }
                int match = is_target(vid, pid);
                if (match) {
                    PHIDP_PREPARSED_DATA pp = NULL;
                    USHORT up = 0, u = 0;
                    if (HidD_GetPreparsedData(h, &pp) && pp) {
                        HIDP_CAPS caps;
                        if (HidP_GetCaps(pp, &caps) == HIDP_STATUS_SUCCESS) {
                            up = caps.UsagePage; u = caps.Usage;
                        }
                        HidD_FreePreparsedData(pp);
                    }
                    // 33/33 channel reports usage 0001:0000 via caps; match by size.
                    if (wantUp == 0x0001 && wantU == 0x0000) {
                        match = (up == 0x0001 && u == 0x0000);
                    } else {
                        match = (up == wantUp && u == wantU);
                    }
                }
                if (match) {
                    if (pathOut) { strncpy(pathOut, det->DevicePath, pathSz - 1); pathOut[pathSz-1] = 0; }
                    found = h; h = INVALID_HANDLE_VALUE; // keep open
                    HeapFree(GetProcessHeap(), 0, buf);
                    break;
                }
                CloseHandle(h);
            }
        }
        HeapFree(GetProcessHeap(), 0, buf);
    }
    SetupDiDestroyDeviceInfoList(set);
    return found;
}

static void hexdump(const unsigned char *b, int n) {
    for (int i = 0; i < n; i++) {
        printf("%02X%c", b[i], (i + 1) % 16 ? ' ' : '\n');
    }
    if (n % 16) printf("\n");
}

// Blocking read with timeout (ms). Returns bytes read, 0 on timeout, -1 on error.
static int read_timeout(HANDLE h, unsigned char *buf, int len, int ms) {
    OVERLAPPED ov;
    memset(&ov, 0, sizeof(ov));
    ov.hEvent = CreateEventA(NULL, TRUE, FALSE, NULL);
    if (!ov.hEvent) return -1;
    DWORD got = 0;
    BOOL ok = ReadFile(h, buf, len, NULL, &ov);
    int ret = -1;
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        DWORD w = WaitForSingleObject(ov.hEvent, ms);
        if (w == WAIT_OBJECT_0 && GetOverlappedResult(h, &ov, &got, FALSE))
            ret = (int)got;
        else {
            CancelIo(h);
            ret = 0; // timeout
        }
    } else if (ok) {
        GetOverlappedResult(h, &ov, &got, FALSE);
        ret = (int)got;
    }
    CloseHandle(ov.hEvent);
    return ret;
}

static int cmd_via(void) {
    // VIA channel: 33-byte reports. Query 0x01 get_protocol_version (read-only).
    char path[512] = {0};
    HANDLE h = open_hid(0x0001, 0x0000, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: 33/33 channel not found/open\n"); return 1; }
    printf("open %s\n", path);
    unsigned char out[33]; memset(out, 0, sizeof(out));
    out[0] = 0x00; // report id
    out[1] = 0x01; // VIA get_protocol_version
    DWORD w = 0;
    OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
    BOOL ok = WriteFile(h, out, sizeof(out), &w, &ov); // overlapped, no event
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        GetOverlappedResult(h, &ov, &w, TRUE);
        ok = TRUE;
    }
    printf("write %lu bytes ok=%d\n", w, ok);
    if (w != sizeof(out)) { printf("WARN short write\n"); }
    for (int i = 0; i < 3; i++) {
        unsigned char in[33]; memset(in, 0, sizeof(in));
        int r = read_timeout(h, in, sizeof(in), 1000);
        if (r <= 0) { printf("read[%d]: timeout\n", i); break; }
        printf("read[%d] %d bytes:\n", i, r);
        hexdump(in, r);
        if (r >= 3 && in[1] == 0x01) { printf("OK via protocol version reply\n"); break; }
    }
    CloseHandle(h);
    return 0;
}

static void ff1c_checksum(unsigned char *r) {
    unsigned sum = 0;
    for (int i = 3; i < 64; i++) sum += r[i];
    r[1] = sum & 0xFF; r[2] = (sum >> 8) & 0xFF;
}

// Send one Layout-A report, collect up to `want` responses. Returns count.
static int ff1c_transact(HANDLE h, unsigned char cmd, unsigned char len,
                         unsigned pos, int want, int ms) {
    unsigned char rep[64]; memset(rep, 0, sizeof(rep));
    rep[0] = 0x04; rep[3] = cmd; rep[4] = len;
    rep[5] = pos & 0xFF; rep[6] = (pos >> 8) & 0xFF; rep[7] = (pos >> 16) & 0xFF;
    ff1c_checksum(rep);
    DWORD w = 0;
    OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
    BOOL ok = WriteFile(h, rep, sizeof(rep), &w, &ov);
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        GetOverlappedResult(h, &ov, &w, TRUE);
        ok = TRUE;
    }
    printf(">> cmd=0x%02X write %lu ok=%d\n", cmd, w, ok);
    int got = 0;
    for (int i = 0; i < want; i++) {
        unsigned char in[64]; memset(in, 0, sizeof(in));
        int r = read_timeout(h, in, sizeof(in), ms);
        if (r <= 0) { printf("<< timeout\n"); break; }
        printf("<< %d bytes:\n", r);
        hexdump(in, r);
        got++;
        if (r >= 4 && in[3] == cmd) break; // ACK / data echo for our cmd
    }
    return got;
}
// Usage: scan [start_hex] [end_hex]. No COMMIT sent, nothing persists.
// Classifies each cmd: ACK-echo / DATA / TIMEOUT.
static int cmd_scan(int argc, char **argv) {
    int start = 0x00, end = 0x20;
    if (argc >= 3) start = (int)strtol(argv[2], NULL, 16) & 0xFF;
    if (argc >= 4) end = (int)strtol(argv[3], NULL, 16) & 0xFF;
    if (start > end || end > 0xFF) { printf("bad range\n"); return 2; }
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("open %s\ncmd : result\n", path);
    for (int cmd = start; cmd <= end; cmd++) {
        if (cmd == 0x02) { printf("0x02: SKIP (commit)\n"); continue; }
        unsigned char rep[64]; memset(rep, 0, sizeof(rep));
        rep[0] = 0x04; rep[3] = (unsigned char)cmd; rep[4] = 0;
        ff1c_checksum(rep);
        DWORD w = 0;
        OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
        BOOL ok = WriteFile(h, rep, sizeof(rep), &w, &ov);
        if (!ok && GetLastError() == ERROR_IO_PENDING) {
            GetOverlappedResult(h, &ov, &w, TRUE);
            ok = TRUE;
        }
        if (!ok || w != 64) { printf("0x%02X: WRITE-FAIL\n", cmd); continue; }
        unsigned char in[64]; memset(in, 0, sizeof(in));
        int r = read_timeout(h, in, sizeof(in), 400);
        if (r <= 0) { printf("0x%02X: TIMEOUT\n", cmd); continue; }
        if (r >= 4 && in[3] == cmd) {
            int nonzero = 0;
            for (int i = 4; i < r; i++) if (in[i]) { nonzero = 1; break; }
            if (nonzero) {
                printf("0x%02X: DATA %d bytes:\n", cmd, r);
                hexdump(in, r);
            } else {
                printf("0x%02X: ACK-echo\n", cmd);
            }
        } else {
            printf("0x%02X: OTHER resp[3]=0x%02X %d bytes:\n", cmd, r >= 4 ? in[3] : 0, r);
            hexdump(in, r);
        }
    }
    CloseHandle(h);
    return 0;
}

// Watch a query cmd: poll N times every Ms ms, print compact payload bytes.
// Usage: watch <cmd_hex> <count> <interval_ms>. Read-only.
static int cmd_watch(int argc, char **argv) {
    if (argc < 5) { printf("usage: timeless82.exe watch <cmd_hex> <count> <interval_ms>\n"); return 2; }
    unsigned cmd = strtoul(argv[2], NULL, 16) & 0xFF;
    int count = atoi(argv[3]);
    int ms = atoi(argv[4]);
    if (cmd == 0x02 || count < 1 || count > 10000 || ms < 50) { printf("bad args\n"); return 2; }
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("polling 0x%02X %d x %dms — change keyboard LEDs now (Fn+Enter, Fn+Up/Down...)\n",
           cmd, count, ms);
    for (int i = 0; i < count; i++) {
        unsigned char rep[64]; memset(rep, 0, sizeof(rep));
        rep[0] = 0x04; rep[3] = (unsigned char)cmd;
        ff1c_checksum(rep);
        DWORD w = 0;
        OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
        BOOL ok = WriteFile(h, rep, sizeof(rep), &w, &ov);
        if (!ok && GetLastError() == ERROR_IO_PENDING)
            GetOverlappedResult(h, &ov, &w, TRUE);
        unsigned char in[64]; memset(in, 0xCC, sizeof(in));
        int r = read_timeout(h, in, sizeof(in), 1500);
        if (r >= 12)
            printf("%04d: %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X\n",
                   i, in[3], in[4], in[5], in[6], in[7], in[8],
                   in[9], in[10], in[11], in[12], in[13], in[14]);
        else
            printf("%04d: NO-REPLY\n", i);
        Sleep(ms);
    }
    CloseHandle(h);
    return 0;
}

// First write trial: INIT,INIT,CONFIG(48 zero bytes @pos0),COMMIT on FF1C.
// Expected: lighting/display goes to baseline (likely LEDs off / clock face).
// Reversible via stock app Apply or Fn combos. Never touches FFEF/OTA.
// Usage: cfgwrite confirm
static int cmd_cfgwrite(int argc, char **argv) {
    if (argc < 3 || strcmp(argv[2], "confirm")) {
        printf("usage: timeless82.exe cfgwrite confirm\n");
        printf("Sends zeroed 48-byte CONFIG + COMMIT to FF1C:0092.\n");
        printf("Expect LEDs/screen to change. Revert: stock app Apply or Fn combos.\n");
        return 2;
    }
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("open %s\n", path);
    // INIT x2
    for (int k = 0; k < 2; k++) {
        unsigned char rep[64]; memset(rep, 0, sizeof(rep));
        rep[0] = 0x04; rep[3] = 0x01;
        ff1c_checksum(rep);
        DWORD w = 0; OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
        WriteFile(h, rep, sizeof(rep), &w, &ov);
        if (GetLastError() == ERROR_IO_PENDING) GetOverlappedResult(h, &ov, &w, TRUE);
        unsigned char in[64];
        int r = read_timeout(h, in, sizeof(in), 2000);
        printf("INIT[%d] ack=%s\n", k, (r >= 4 && in[3] == 0x01) ? "yes" : "NO");
    }
    // CONFIG: 48 zero bytes at pos 0 (Layout A)
    {
        unsigned char rep[64]; memset(rep, 0, sizeof(rep));
        rep[0] = 0x04; rep[3] = 0x06; rep[4] = 48; // pos already 0
        ff1c_checksum(rep);
        DWORD w = 0; OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
        WriteFile(h, rep, sizeof(rep), &w, &ov);
        if (GetLastError() == ERROR_IO_PENDING) GetOverlappedResult(h, &ov, &w, TRUE);
        unsigned char in[64];
        int r = read_timeout(h, in, sizeof(in), 2000);
        printf("CONFIG ack=%s\n", (r >= 4 && in[3] == 0x06) ? "yes" : "NO");
    }
    // COMMIT
    {
        unsigned char rep[64]; memset(rep, 0, sizeof(rep));
        rep[0] = 0x04; rep[3] = 0x02;
        ff1c_checksum(rep);
        DWORD w = 0; OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
        WriteFile(h, rep, sizeof(rep), &w, &ov);
        if (GetLastError() == ERROR_IO_PENDING) GetOverlappedResult(h, &ov, &w, TRUE);
        unsigned char in[64];
        int r = read_timeout(h, in, sizeof(in), 2000);
        printf("COMMIT ack=%s\n", (r >= 4 && in[3] == 0x02) ? "yes" : "NO");
    }
    CloseHandle(h);
    printf("done — report what changed on keyboard + OLED\n");
    return 0;
}

// Send one Layout-A report on FF1C and wait for ACK (resp[3]==cmd).
// Returns 1 on ACK, 0 on timeout/fail. Retries up to 3 times.
static int ff1c_sendA(HANDLE h, unsigned char cmd, unsigned char len,
                      unsigned pos, const unsigned char *data, int verbose) {
    for (int attempt = 0; attempt < 3; attempt++) {
        unsigned char rep[64]; memset(rep, 0, sizeof(rep));
        rep[0] = 0x04; rep[3] = cmd; rep[4] = len;
        rep[5] = pos & 0xFF; rep[6] = (pos >> 8) & 0xFF; rep[7] = (pos >> 16) & 0xFF;
        if (data && len) memcpy(rep + 8, data, len > 56 ? 56 : len);
        ff1c_checksum(rep);
        DWORD w = 0; OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
        BOOL ok = WriteFile(h, rep, sizeof(rep), &w, &ov);
        if (!ok && GetLastError() == ERROR_IO_PENDING)
            ok = GetOverlappedResult(h, &ov, &w, TRUE);
        if (!ok || w != 64) {
            if (verbose) printf("cmd 0x%02X write-fail err=%lu\n", cmd, GetLastError());
            continue;
        }
        for (int i = 0; i < 3; i++) {
            unsigned char in[64]; memset(in, 0, sizeof(in));
            int r = read_timeout(h, in, sizeof(in), 2000);
            if (r <= 0) break;
            if (r >= 4 && in[3] == cmd) return 1;
            // discard non-matching (stale echo), keep reading
        }
        if (verbose) printf("cmd 0x%02X no-ack attempt %d\n", cmd, attempt);
    }
    return 0;
}

// Drain stale input reports (e.g. unconsumed ACKs). Read-only.
static void ff1c_drain(HANDLE h) {
    for (int i = 0; i < 64; i++) {
        unsigned char in[64];
        if (read_timeout(h, in, sizeof(in), 50) <= 0) break;
    }
}

// Custom CONFIG write: cfg OFF:VAL ... (hex). Base = 48 zero bytes.
// Full sequence INIT,INIT,CONFIG,COMMIT. Reversible via stock app Apply.
static int cmd_cfg(int argc, char **argv) {
    if (argc < 3) {
        printf("usage: timeless82.exe cfg OFF:VAL ...  (hex, off 00..2F)\n");
        return 2;
    }
    unsigned char cfgbuf[48]; memset(cfgbuf, 0, sizeof(cfgbuf));
    for (int i = 2; i < argc; i++) {
        unsigned off, val;
        if (sscanf(argv[i], "%x:%x", &off, &val) != 2 || off > 47 || val > 0xFF) {
            printf("bad pair '%s'\n", argv[i]); return 2;
        }
        cfgbuf[off] = (unsigned char)val;
    }
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("open %s\n", path);
    ff1c_drain(h);
    printf("INIT %s\n", ff1c_sendA(h, 0x01, 0, 0, NULL, 1) ? "ack" : "NO-ACK");
    printf("INIT %s\n", ff1c_sendA(h, 0x01, 0, 0, NULL, 1) ? "ack" : "NO-ACK");
    printf("CONFIG %s\n", ff1c_sendA(h, 0x06, 48, 0, cfgbuf, 1) ? "ack" : "NO-ACK");
    printf("COMMIT %s\n", ff1c_sendA(h, 0x02, 0, 0, NULL, 1) ? "ack" : "NO-ACK");
    CloseHandle(h);
    printf("done — report LEDs + OLED\n");
    return 0;
}

// OLED upload trial: oled FILE [NFRAMES=1] [DISP_IDX=1].// FILE = raw 8192-byte frames (128x64, 1 byte/px). Sequence per Evision/Telink
// display pipeline: INIT,INIT,CONFIG,COMMIT,0x23,INIT,IMAGE xN,COMMIT.
static int cmd_oled(int argc, char **argv) {
    if (argc < 3) {
        printf("usage: timeless82.exe oled FILE [NFRAMES=1] [DISP_IDX=1]\n");
        return 2;
    }
    int nframes = argc >= 4 ? atoi(argv[3]) : 1;
    int dispidx = argc >= 5 ? atoi(argv[4]) : 1;
    if (nframes < 1 || nframes > 21 || dispidx < 0 || dispidx > 2) { printf("bad args\n"); return 2; }
    FILE *f = fopen(argv[2], "rb");
    if (!f) { printf("cannot open %s\n", argv[2]); return 1; }
    long want = (long)nframes * 8192L;
    unsigned char *pix = (unsigned char *)malloc(want);
    if (!pix) { fclose(f); printf("oom\n"); return 1; }
    long got = (long)fread(pix, 1, want, f);
    fclose(f);
    if (got != want) { printf("file has %ld bytes, need %ld\n", got, want); free(pix); return 1; }
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { free(pix); printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("open %s\nupload %d frame(s), disp_idx=%d\n", path, nframes, dispidx);
    ff1c_drain(h);
    unsigned char cfgbuf[48];
    memset(cfgbuf, 0, sizeof(cfgbuf));
    cfgbuf[33] = (unsigned char)dispidx;
    cfgbuf[34] = (unsigned char)nframes;
    cfgbuf[43] = 100; // frame interval 100ms
    int ok = 1;
    ok &= ff1c_sendA(h, 0x01, 0, 0, NULL, 1);
    ok &= ff1c_sendA(h, 0x01, 0, 0, NULL, 1);
    ok &= ff1c_sendA(h, 0x06, 48, 0, cfgbuf, 1);
    ok &= ff1c_sendA(h, 0x02, 0, 0, NULL, 1);
    ok &= ff1c_sendA(h, 0x23, 0, 0, NULL, 1);
    ok &= ff1c_sendA(h, 0x01, 0, 0, NULL, 1);
    printf("preamble %s\n", ok ? "all-ack" : "SOME-NO-ACK");
    if (!ok) { printf("aborting before pixel data\n"); CloseHandle(h); free(pix); return 1; }
    long total = want, sent = 0, pos = 0;
    int fail = 0;
    while (sent < total) {
        int chunk = (int)((total - sent > 56) ? 56 : (total - sent));
        if (!ff1c_sendA(h, 0x21, (unsigned char)chunk, (unsigned)pos, pix + sent, 0)) {
            printf("IMAGE fail at pos %ld\n", pos); fail = 1; break;
        }
        sent += chunk; pos += chunk;
        if ((pos / 56) % 25 == 0) printf("... %ld/%ld\n", sent, total);
    }
    if (!fail) printf("IMAGE done %s\n", ff1c_sendA(h, 0x02, 0, 0, NULL, 1) ? "COMMIT-ack" : "COMMIT-NO-ACK");
    CloseHandle(h); free(pix);
    printf("done — report OLED\n");
    return fail ? 1 : 0;
}

// OLED frame upload, Frida-proven wire format (hidfrida.log).
// FILE = N concatenated 1024B frames, no stock app needed.
// Pixel encoding: 1024B/frame column-major 1-bit MSB-top:
// byte[c*8+pg] bit 7-k = pixel (pg*8+k, c).
// 64B WriteFile reports: [0]=0x04 [1..2]=checksum u16LE sum[3..63]
// [3]=cmd [4]=len [5..7]=pos LE24 [8..63]=payload.
// Usage: oledN FILE NFRAMES [DISP_IDX=4] [INTERVAL=1000].
// N = 1..255 (128 is the verified hardware playback cap).
// Sequence: INIT(0x01)x1, IMAGE(0x21, 56B chunks, pos 0..N*1024-1),
// COMMIT(0x02), INIT, CONFIG(0x06 len 56), COMMIT. No 0x23.
// CONFIG layout (offsets into the 56B payload = config buffer from byte 0;
// gmk87-c-spec 240x135 sibling, confirmed by capture):
//   [22]=0x03 magic, [33]=disp_idx (0-based screen index: 4 = screen 5),
//   [34]=nframes, [35..37]=BCD clock sec/min/hour (capture 39 55 18 = 18:55:57),
//   [43..44]=frame interval u16 LE MILLISECONDS (capture 00 00;
//   larger = slower; old oled used 100ms). Earlier oledN wrongly wrote the
//   interval into the clock byte [35], so the knob had no visible effect.
// The board stalls its keyboard scanning while ingesting IMAGE data, and
// the transfer is firmware-paced (~7s for 107 frames; per-chunk ACK wait is
// optimal, fire-and-forget is slower because the IN buffer backs up). So
// nowlive.py gates uploads on user idle instead of trying to go faster.
// Only FF1C:0092 on wired 320F:5055 (open_hid refuses FFEF);
// never sends 0xBE 0xFC / 0xBE 0xEE.
static int cmd_oledN(int argc, char **argv) {
    if (argc < 4) {
        printf("usage: timeless82.exe oledN FILE NFRAMES [DISP_IDX=4] [INTERVAL=1000]\n");
        return 2;
    }
    int nframes = atoi(argv[3]);
    int dispidx = argc >= 5 ? atoi(argv[4]) : 4;
    int interval = argc >= 6 ? atoi(argv[5]) : 1000;
    if (nframes < 1 || nframes > 255) { printf("bad NFRAMES (1..255)\n"); return 2; }
    if (dispidx < 0 || dispidx > 5) { printf("bad DISP_IDX (0..5, 4=screen 5)\n"); return 2; }
    if (interval < 1 || interval > 60000) { printf("bad INTERVAL (1..60000 ms)\n"); return 2; }
    FILE *f = fopen(argv[2], "rb");
    if (!f) { printf("cannot open %s\n", argv[2]); return 1; }
    const long want = (long)nframes * 1024L;
    unsigned char *pix = (unsigned char *)malloc(want);
    if (!pix) { fclose(f); printf("oom\n"); return 1; }
    long got = (long)fread(pix, 1, want, f);
    fclose(f);
    if (got != want) { printf("file has %ld bytes, need %ld (%dx1024)\n", got, want, nframes); free(pix); return 1; }
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { free(pix); printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("open %s\nupload %d frame(s), disp_idx=%d interval=%d\n", path, nframes, dispidx, interval);
    ff1c_drain(h);
    if (!ff1c_sendA(h, 0x01, 0, 0, NULL, 1)) {
        printf("INIT NO-ACK, aborting before pixel data\n");
        CloseHandle(h); free(pix); return 1;
    }
    printf("INIT ack\n");
    long sent = 0, pos = 0;
    int fail = 0;
    while (sent < want) {
        int chunk = (int)((want - sent > 56) ? 56 : (want - sent));
        if (!ff1c_sendA(h, 0x21, (unsigned char)chunk, (unsigned)pos, pix + sent, 0)) {
            printf("IMAGE fail at pos %ld\n", pos); fail = 1; break;
        }
        sent += chunk; pos += chunk;
        if ((pos / 56) % 25 == 0) printf("... %ld/%ld\n", sent, want);
    }
    if (fail) { CloseHandle(h); free(pix); return 1; }
    printf("IMAGE done %ld bytes\n", sent);
    unsigned char cfg[56]; memset(cfg, 0, sizeof(cfg));
    cfg[22] = 0x03;
    cfg[33] = (unsigned char)dispidx;
    cfg[34] = (unsigned char)nframes;
    // [35..37] BCD clock (seconds, minutes, hours) — same field stock sent.
    time_t now = time(NULL); struct tm *lt = localtime(&now);
    if (lt) {
        cfg[35] = (unsigned char)(((lt->tm_sec / 10) << 4) | (lt->tm_sec % 10));
        cfg[36] = (unsigned char)(((lt->tm_min / 10) << 4) | (lt->tm_min % 10));
        cfg[37] = (unsigned char)(((lt->tm_hour / 10) << 4) | (lt->tm_hour % 10));
    }
    // [43..44] frame interval u16 LE milliseconds: larger = slower.
    cfg[43] = (unsigned char)(interval & 0xFF);
    cfg[44] = (unsigned char)((interval >> 8) & 0xFF);
    int ok = 1, r;
    r = ff1c_sendA(h, 0x02, 0, 0, NULL, 1); printf("COMMIT %s\n", r ? "ack" : "NO-ACK"); ok &= r;
    r = ff1c_sendA(h, 0x01, 0, 0, NULL, 1); printf("INIT %s\n", r ? "ack" : "NO-ACK"); ok &= r;
    r = ff1c_sendA(h, 0x06, 56, 0, cfg, 1); printf("CONFIG %s\n", r ? "ack" : "NO-ACK"); ok &= r;
    r = ff1c_sendA(h, 0x02, 0, 0, NULL, 1); printf("COMMIT %s\n", r ? "ack" : "NO-ACK"); ok &= r;
    CloseHandle(h); free(pix);
    printf("done — report OLED\n");
    return ok ? 0 : 1;
}

// OLED pixel path (rev-engineered from stock app screen-upload function):
// 17-byte HidD_SetOutputReport reports: [FF][B1][B2][13 payload bytes].
// 12 sends per 39-byte chunk, headers cycle:
//   {22,AA}x7B {22,AD}x6B {44,AA}x7B {44,AD}x6B {22,AB}x7B {22,AE}x6B
//   {44,AB}x7B {44,AE}x6B {22,AC}x7B {22,AF}x6B {44,AC}x7B {44,AF}x6B
// Payload bytes clamped to 0xF7 (stock app behavior).
// Usage: oled2 FILE [OFFSET=0] [NBYTES=39]. Read-only except the reports.
static int cmd_oled2(int argc, char **argv) {
    if (argc < 3) {
        printf("usage: timeless82.exe oled2 FILE [OFFSET=0] [NBYTES=39]\n");
        return 2;
    }
    long off = argc >= 4 ? atol(argv[3]) : 0;
    long n = argc >= 5 ? atol(argv[4]) : 39;
    if (off < 0 || n < 1 || n > 8192 || off + n > 8192) { printf("bad range\n"); return 2; }
    FILE *f = fopen(argv[2], "rb");
    if (!f) { printf("cannot open %s\n", argv[2]); return 1; }
    unsigned char frame[8192];
    if ((long)fread(frame, 1, 8192, f) != 8192) { printf("need 8192 bytes\n"); fclose(f); return 1; }
    fclose(f);
    for (long i = off; i < off + n; i++)
        if (frame[i] > 0xF7) frame[i] = 0xF7;
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("open %s\n", path);
    static const unsigned char H[12][3] = {
        {0xFF,0x22,0xAA},{0xFF,0x22,0xAD},{0xFF,0x44,0xAA},{0xFF,0x44,0xAD},
        {0xFF,0x22,0xAB},{0xFF,0x22,0xAE},{0xFF,0x44,0xAB},{0xFF,0x44,0xAE},
        {0xFF,0x22,0xAC},{0xFF,0x22,0xAF},{0xFF,0x44,0xAC},{0xFF,0x44,0xAF}};
    static const int CNT[12] = {7,6,7,6,7,6,7,6,7,6,7,6};
    // staging: 39 bytes, sent twice (S1&S3 share -0x40 etc. per disasm =
    // contiguous areas, each 13B: area k bytes [k*13 .. k*13+12]).
    // S1: area0[0..6] S2: area0[7..12] S3: area0[0..6]?? -> replicate: send
    // chunk bytes twice with the two header variants is WRONG; instead follow
    // the byte flow literally: S1=stg[0..6] S2=stg[7..12] S3=stg[0..6]...
    // We send the first 39-byte group once (S1..S12 pattern needs 78B);
    // pad second copy with zeros. Simplest faithful first probe: S1,S2 only.
    long pos = off;
    long left = n;
    int grp = 0;
    // full 12-send groups while >=78B remain, else partial S1/S2
    while (left > 0) {
        for (int s = 0; s < 12 && left > 0; s++) {
            unsigned char rep[17];
            rep[0] = H[s][0]; rep[1] = H[s][1]; rep[2] = H[s][2]; rep[3] = 0x00;
            int c = CNT[s];
            if (c > left) c = (int)left;
            memset(rep + 4, 0, 13);
            memcpy(rep + 4, frame + pos, c);
            BOOL ok = HidD_SetOutputReport(h, rep, sizeof(rep));
            printf("S%-2d [%02X %02X %02X] %dB @%ld -> %s err=%lu\n",
                   s + 1, rep[0], rep[1], rep[2], c, pos, ok ? "OK" : "FAIL", ok ? 0 : GetLastError());
            if (!ok) { CloseHandle(h); return 1; }
            pos += c; left -= c;
            grp++;
            if (grp >= 2 && n <= 78) break; // first probe: S1+S2 only for small n
        }
        if (n <= 78) break;
    }
    CloseHandle(h);
    printf("done — report OLED + return codes\n");
    return 0;
}

// Sweep 17-byte [FF 22 AA ...] SetOutputReport on WIRED 320F:5055 ONLY.
// NEVER touch OTA (usagePage FFEF / featLen>0 / MI_02), NEVER touch 25A7
// dongle, NEVER send DFU. Only outLen==17 or outLen==33 are candidates;
// others reported as SKIP, no write. Single zero packet per interface.
static int cmd_sweep17(int argc, char **argv) {
    (void)argc; (void)argv;
    GUID guid;
    HidD_GetHidGuid(&guid);
    HDEVINFO set = SetupDiGetClassDevsA(&guid, NULL, NULL,
                                        DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (set == INVALID_HANDLE_VALUE) { printf("ERR enum\n"); return 1; }
    unsigned char rep[17];
    rep[0]=0xFF; rep[1]=0x22; rep[2]=0xAA; rep[3]=0x00;
    memset(rep+4, 0, 13);
    DWORD idx = 0;
    SP_DEVICE_INTERFACE_DATA ifd; ifd.cbSize = sizeof(ifd);
    while (SetupDiEnumDeviceInterfaces(set, NULL, &guid, idx, &ifd)) {
        idx++;
        DWORD need = 0;
        SetupDiGetDeviceInterfaceDetailA(set, &ifd, NULL, 0, &need, NULL);
        if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) continue;
        char *buf = (char *)HeapAlloc(GetProcessHeap(), 0, need + 2);
        if (!buf) continue;
        SP_DEVICE_INTERFACE_DETAIL_DATA_A *det = (SP_DEVICE_INTERFACE_DETAIL_DATA_A *)buf;
        det->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_A);
        if (!SetupDiGetDeviceInterfaceDetailA(set, &ifd, det, need, NULL, NULL)) {
            HeapFree(GetProcessHeap(), 0, buf); continue;
        }
        HANDLE h = CreateFileA(det->DevicePath, GENERIC_READ | GENERIC_WRITE,
                               FILE_SHARE_READ | FILE_SHARE_WRITE,
                               NULL, OPEN_EXISTING, 0, NULL);
        if (h == INVALID_HANDLE_VALUE) {
            HeapFree(GetProcessHeap(), 0, buf); continue;
        }
        HIDD_ATTRIBUTES attr; attr.Size = sizeof(attr);
        USHORT vid = 0, pid = 0, up = 0, u = 0;
        USHORT inL = 0, outL = 0, featL = 0;
        if (HidD_GetAttributes(h, &attr)) { vid = attr.VendorID; pid = attr.ProductID; }
        PHIDP_PREPARSED_DATA pp = NULL;
        if (HidD_GetPreparsedData(h, &pp) && pp) {
            HIDP_CAPS caps;
            if (HidP_GetCaps(pp, &caps) == HIDP_STATUS_SUCCESS) {
                up = caps.UsagePage; u = caps.Usage;
                inL = caps.InputReportByteLength; outL = caps.OutputReportByteLength;
                featL = caps.FeatureReportByteLength;
            }
            HidD_FreePreparsedData(pp);
        }
        int isWired = (vid == 0x320F && pid == 0x5055);
        int isOTA = (up == 0xFFEF) || (featL > 0);
        int isDongle = (vid == 0x25A7);
        if (!isWired || isOTA || isDongle || outL == 0) {
            printf("SKIP %04X:%04X up=%04X u=%04X in=%u out=%u feat=%u%s%s\n    %s\n",
                   vid, pid, up, u, inL, outL, featL,
                   isOTA ? " [OTA-NEVER]" : "",
                   isDongle ? " [DONGLE-NEVER]" : "",
                   det->DevicePath);
            CloseHandle(h);
            HeapFree(GetProcessHeap(), 0, buf);
            continue;
        }
        int candidate = (outL == 17 || outL == 33);
        if (candidate) {
            BOOL ok = HidD_SetOutputReport(h, rep, sizeof(rep));
            printf("%04X:%04X up=%04X u=%04X in=%u out=%u feat=%u -> %s err=%lu\n    %s\n",
                   vid, pid, up, u, inL, outL, featL,
                   ok ? "OK" : "fail", ok ? 0 : GetLastError(), det->DevicePath);
        } else {
            printf("SKIP %04X:%04X up=%04X u=%04X in=%u out=%u feat=%u [not-17/33]\n    %s\n",
                   vid, pid, up, u, inL, outL, featL, det->DevicePath);
        }
        CloseHandle(h);
        HeapFree(GetProcessHeap(), 0, buf);
    }
    SetupDiDestroyDeviceInfoList(set);
    return 0;
}

// Generic parameterized query: q <cmd_hex> <len_dec> <pos_hex>.
// Sends Layout-A with zero payload, dumps up to 4 responses. No COMMIT.
static int cmd_q(int argc, char **argv) {
    if (argc < 5) { printf("usage: timeless82.exe q <cmd_hex> <len_dec> <pos_hex>\n"); return 2; }
    unsigned cmd = strtoul(argv[2], NULL, 16) & 0xFF;
    int len = atoi(argv[3]);
    unsigned pos = strtoul(argv[4], NULL, 16);
    if (cmd == 0x02) { printf("REFUSED: commit\n"); return 2; }
    if (len < 0 || len > 56) { printf("bad len (0..56)\n"); return 2; }
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    unsigned char rep[64]; memset(rep, 0, sizeof(rep));
    rep[0] = 0x04; rep[3] = (unsigned char)cmd; rep[4] = (unsigned char)len;
    rep[5] = pos & 0xFF; rep[6] = (pos >> 8) & 0xFF; rep[7] = (pos >> 16) & 0xFF;
    ff1c_checksum(rep);
    DWORD w = 0;
    OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
    BOOL ok = WriteFile(h, rep, sizeof(rep), &w, &ov);
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        GetOverlappedResult(h, &ov, &w, TRUE);
        ok = TRUE;
    }
    printf(">> cmd=0x%02X len=%d pos=0x%X write %lu ok=%d\n", cmd, len, pos, w, ok);
    for (int i = 0; i < 4; i++) {
        unsigned char in[64]; memset(in, 0, sizeof(in));
        int r = read_timeout(h, in, sizeof(in), 1500);
        if (r <= 0) { printf("<< timeout\n"); break; }
        printf("<< %d bytes:\n", r);
        hexdump(in, r);
        if (r >= 4 && in[3] == cmd && i > 0) break;
    }
    CloseHandle(h);
    return 0;
}

static int cmd_readcfg(void) {    // Read-only: ask device for its config buffer (Node impl uses 0x05/0x03).
    // No writes that change state; no COMMIT. Dumps whatever comes back.
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("open %s\n", path);
    printf("--- try 0x05 ---\n");
    ff1c_transact(h, 0x05, 0, 0, 3, 2000);
    printf("--- try 0x03 ---\n");
    ff1c_transact(h, 0x03, 0, 0, 3, 2000);
    CloseHandle(h);
    return 0;
}

static int cmd_ping(void) {
    // FF1C:0092 transport check: Layout-A INIT (0x01), no data, wait for ACK.
    // No COMMIT is sent, so nothing persists. Watch keyboard: expect no change.
    char path[512] = {0};
    HANDLE h = open_hid(0xFF1C, 0x92, path, sizeof(path));
    if (h == INVALID_HANDLE_VALUE) { printf("ERR: FF1C:0092 not found/open\n"); return 1; }
    printf("open %s\n", path);
    unsigned char rep[64]; memset(rep, 0, sizeof(rep));
    rep[0] = 0x04; rep[3] = 0x01; rep[4] = 0x00; // INIT, len 0, pos 0
    ff1c_checksum(rep);
    DWORD w = 0;
    OVERLAPPED ov; memset(&ov, 0, sizeof(ov));
    BOOL ok = WriteFile(h, rep, sizeof(rep), &w, &ov);
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        GetOverlappedResult(h, &ov, &w, TRUE);
        ok = TRUE;
    }
    printf("write %lu bytes ok=%d cs=%02X%02X\n", w, ok, rep[2], rep[1]);
    int acked = 0;
    for (int i = 0; i < 5; i++) {
        unsigned char in[64]; memset(in, 0, sizeof(in));
        int r = read_timeout(h, in, sizeof(in), 2000);
        if (r <= 0) { printf("read[%d]: timeout\n", i); break; }
        printf("read[%d] %d bytes: %02X %02X %02X %02X %02X %02X %02X %02X ...\n",
               i, r, in[0], in[1], in[2], in[3], in[4], in[5], in[6], in[7]);
        if (r >= 4 && in[3] == 0x01) { acked = 1; break; } // ACK, discard others
    }
    printf(acked ? "OK ff1c transport alive (ACK 0x01)\n" : "NO-ACK on 0x01\n");
    CloseHandle(h);
    return acked ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("usage: timeless82.exe <list|caps|via|ping>\n");
        return 2;
    }
    if (!strcmp(argv[1], "list")) return cmd_list();
    if (!strcmp(argv[1], "caps")) return cmd_caps();
    if (!strcmp(argv[1], "via")) return cmd_via();
    if (!strcmp(argv[1], "ping")) return cmd_ping();
    if (!strcmp(argv[1], "readcfg")) return cmd_readcfg();
    if (!strcmp(argv[1], "scan")) return cmd_scan(argc, argv);
    if (!strcmp(argv[1], "q")) return cmd_q(argc, argv);
    if (!strcmp(argv[1], "watch")) return cmd_watch(argc, argv);
    if (!strcmp(argv[1], "cfgwrite")) return cmd_cfgwrite(argc, argv);
    if (!strcmp(argv[1], "cfg")) return cmd_cfg(argc, argv);
    if (!strcmp(argv[1], "oled")) return cmd_oled(argc, argv);
    if (!strcmp(argv[1], "oled30")) return cmd_oledN(argc, argv); // alias
    if (!strcmp(argv[1], "oledN")) return cmd_oledN(argc, argv);
    if (!strcmp(argv[1], "oled2")) return cmd_oled2(argc, argv);
    if (!strcmp(argv[1], "sweep17")) return cmd_sweep17(argc, argv);
    printf("unknown cmd '%s'. usage: timeless82.exe <list|caps|via|ping|readcfg|scan|q|watch|cfgwrite|cfg|oled|oledN|oled2|sweep17>\n", argv[1]);
    return 2;
}
