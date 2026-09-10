// Frida agent v2: null-safe lazy hooks (hid.dll may load after us).
send({t: 'agent-start'});
var paths = {};
var hooked = {};
function exactMod(want) {
  var found = null;
  try {
    var mods = Process.enumerateModules();
    for (var i = 0; i < mods.length; i++) {
      if (mods[i].name.toLowerCase() === want) { found = mods[i].name; break; }
    }
  } catch (e) {}
  return found;
}
function tryHook(mod, exp, mk) {
  if (hooked[exp]) return true;
  var addr = null;
  try {
    var real = exactMod(mod);
    if (real !== null)
      addr = Process.getModuleByName(real).getExportByName(exp);
  } catch (e) { addr = null; }
  if (addr === null) {
    try { addr = Module.getGlobalExportByName(exp); }
    catch (e) { addr = null; }
  }
  if (addr === null) {
    send({t: 'miss', what: mod + '!' + exp});
    return false;
  }
  try {
    Interceptor.attach(addr, mk());
    hooked[exp] = true;
    send({t: 'hooked', what: mod + '!' + exp});
  } catch (e) {
    send({t: 'err', what: exp + ' attach: ' + e});
  }
  return !!hooked[exp];
}
function isKb(h) {
  var p = paths[h];
  return p && p.toLowerCase().indexOf('vid_320f') !== -1;
}
function hookAll() {
  tryHook('kernel32.dll', 'CreateFileW', function () {
    return {
      onEnter: function (args) { this.p = args[0].readUtf16String(); },
      onLeave: function (retval) {
        var h = retval.toString();
        if (this.p && this.p.toLowerCase().indexOf('hid#') !== -1) {
          paths[h] = this.p;
          send({t: 'open', h: h, path: this.p});
        }
      }
    };
  });
  tryHook('hid.dll', 'HidD_SetOutputReport', function () {
    return {
      onEnter: function (args) {
        this.h = args[0].toString(); this.b = args[1];
        this.n = args[2].toInt32();
      },
      onLeave: function (retval) {
        // log ALL: diffusion/ioctl paths may use pre-hook handles
        var m = Math.min(this.n, 128);
        send({t: 'SOR', h: this.h, len: this.n, ok: retval.toInt32()},
             this.b.readByteArray(m));
      }
    };
  });
  tryHook('hid.dll', 'HidD_SetFeature', function () {
    return {
      onEnter: function (args) {
        this.h = args[0].toString(); this.b = args[1];
        this.n = args[2].toInt32();
      },
      onLeave: function (retval) {
        var m = Math.min(this.n, 128);
        send({t: 'SFeat', h: this.h, len: this.n, ok: retval.toInt32()},
             this.b.readByteArray(m));
      }
    };
  });
  var wfCount = {};
  function hidCode(code) { return (((code >>> 0) & 0xFFFF0000) === 0xB0000); }  tryHook('kernel32.dll', 'WriteFile', function () {
    return {
      onEnter: function (args) {
        this.h = args[0].toString(); this.b = args[1];
        try { this.n = args[2].toInt32(); } catch (e) { this.n = 0; }
      },
      onLeave: function (retval) {
        // 320F handles always; unknown handles capped (file-write floods)
        var known = (this.h in paths);
        if (known && !isKb(this.h)) return;
        wfCount[this.h] = (wfCount[this.h] || 0) + 1;
        if (!known && wfCount[this.h] > 5000) return;
        var m = Math.min(this.n, 96);
        if (m <= 0) return;
        try {
          send({t: 'WF', h: this.h, len: this.n, ok: retval.toInt32()},
               this.b.readByteArray(m));
        } catch (e) {}
      }
    };
  });
  var ioCount = {};
  tryHook('kernel32.dll', 'DeviceIoControl', function () {    return {
      onEnter: function (args) {
        this.h = args[0].toString();
        try { this.code = args[1].toInt32(); } catch (e) { this.code = 0; }
        this.ib = args[2];
        try { this.il = args[3].toInt32(); } catch (e) { this.il = 0; }
      },
      onLeave: function (retval) {
        var known = (this.h in paths);
        if (known && !isKb(this.h)) return;
        // only HID-class IOCTLs (0xB....) or known-320F handles; else noise
        if (!known && !hidCode(this.code)) return;
        ioCount[this.h] = (ioCount[this.h] || 0) + 1;
        if (!known && ioCount[this.h] > 5000) return;
        var m = Math.min(this.il, 64);
        try {
          var ab = m > 0 ? this.ib.readByteArray(m) : null;
          send({t: 'IO', h: this.h, code: this.code, len: this.il,
                ok: retval.toInt32()}, ab);
        } catch (e) {}
      }
    };
  });
  var ntIoCount = {};
  tryHook('ntdll.dll', 'NtDeviceIoControlFile', function () {    return {
      onEnter: function (args) {
        this.h = args[0].toString();
        try { this.code = args[5].toInt32(); } catch (e) { this.code = 0; }
        this.ib = args[6];
        try { this.il = args[7].toInt32(); } catch (e) { this.il = 0; }
      },
      onLeave: function (retval) {
        var known = (this.h in paths);
        if (known && !isKb(this.h)) return;
        // only HID-class IOCTLs (0xB....) or known-320F handles; else noise
        if (!known && !hidCode(this.code)) return;
        ntIoCount[this.h] = (ntIoCount[this.h] || 0) + 1;
        if (!known && ntIoCount[this.h] > 5000) return;
        var m = Math.min(this.il, 64);
        try {
          var ab = m > 0 ? this.ib.readByteArray(m) : null;
          send({t: 'NTIO', h: this.h, code: this.code, len: this.il,
                ok: retval.toInt32()}, ab);
        } catch (e) {}
      }
    };
  });
  tryHook('user32.dll', 'MessageBoxW', function () {
    return {
      onEnter: function (args) {
        try { this.tx = args[1].readUtf16String(); } catch (e) { this.tx = ''; }
        try { this.cp = args[2].readUtf16String(); } catch (e) { this.cp = ''; }
      },
      onLeave: function (retval) {
        send({t: 'MSGBOX', cap: this.cp, txt: this.tx});
      }
    };
  });
  tryHook('kernel32.dll', 'CreateProcessW', function () {
    return {
      onEnter: function (args) {
        try { this.app = args[0].isNull() ? '' : args[0].readUtf16String(); } catch (e) { this.app = ''; }
        try { this.cmd = args[1].isNull() ? '' : args[1].readUtf16String(); } catch (e) { this.cmd = ''; }
      },
      onLeave: function (retval) {
        send({t: 'PROC', ok: retval.toInt32(), app: this.app, cmd: this.cmd});
      }
    };
  });
}
hookAll();
setInterval(hookAll, 2000);  // catch late loads (hid.dll often loads later)
send({t: 'agent-ready'});
