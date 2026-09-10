// Hook-resolution self-test: expect 'hooked kernel32.dll!CreateFileW'.
send({t: 'agent-start'});
try {
  var addr = Module.getExportByName('KERNEL32.DLL', 'CreateFileW');
  Interceptor.attach(addr, { onEnter: function (args) {} });
  send({t: 'hooked', what: 'kernel32.dll!CreateFileW'});
} catch (e) { send({t: 'fail', what: String(e).substring(0, 120)}); }
send({t: 'agent-ready'});
