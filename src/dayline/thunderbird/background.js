// The native connection launches a small Python broker, not another sync client.
let port;
let queue = Promise.resolve();
let changeTimer = null;

function connect() {
  port = browser.runtime.connectNative("io.github.wusitee.dayline");
  const connection = port;
  port.onMessage.addListener(request => {
    queue = queue.then(async () => {
      let reply;
      try {
        reply = { id: request.id, result: await browser.daylineCalendar.execute(request) };
      } catch (error) {
        reply = { id: request.id, error: error.message || String(error) };
      }
      try {
        connection.postMessage(reply);
      } catch (_) {
        // A reply to a closed native connection cannot be delivered.
      }
    });
  });
  port.onDisconnect.addListener(() => {
    port = null;
    setTimeout(connect, 10000);
  });
}

browser.daylineCalendar.onChanged.addListener(() => {
  if (changeTimer === null) {
    changeTimer = setTimeout(() => {
      changeTimer = null;
      if (port) {
        port.postMessage({ event: "changed" });
      }
    }, 1000);
  }
});
connect();
