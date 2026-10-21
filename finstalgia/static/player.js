/* Optional ES5 enhancement for native video. */
(function () {
    "use strict";
    var video = document.getElementById("player");
    if (!video || !window.XMLHttpRequest) { return; }
    var status = document.getElementById("save-status");
    var endpoint = video.getAttribute("data-report");
    var csrf = video.getAttribute("data-csrf");
    var target = Number(video.getAttribute("data-resume")) / 10000000;
    var restoring = target > 0;
    var started = false;
    var sentStart = false;
    var sending = false;
    var queued = null;
    var disabled = false;
    var lastSent = 0;
    function message(text) { if (status) { status.textContent = text; } }
    function restore() {
        if (!restoring || video.readyState < 1) { return; }
        try {
            video.currentTime = target;
            restoring = Math.abs(video.currentTime - target) > 2;
        } catch (ignore) { /* Retry when the native HLS timeline is ready. */ }
    }
    function transmit(report) {
        if (disabled) { return; }
        if (sending) {
            if (!queued || queued.event !== "ended") { queued = report; }
            return;
        }
        sending = true;
        var xhr = new XMLHttpRequest();
        xhr.open("POST", endpoint, true);
        xhr.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
        xhr.timeout = 15000;
        var finished = false;
        function finish(ok) {
            if (finished) { return; }
            finished = true;
            sending = false;
            if (ok) { message(report.event === "ended" ? "Finished" : "Progress saved"); }
            else if (xhr.status === 401 || xhr.status === 403) {
                disabled = true;
                message("Sign in again to save progress.");
            } else { message("Progress could not be saved. Retrying while you watch."); }
            if (queued && !disabled) {
                var next = queued;
                queued = null;
                transmit(next);
            }
        }
        xhr.onreadystatechange = function () {
            if (xhr.readyState === 4) { finish(xhr.status === 204); }
        };
        xhr.onerror = function () { finish(false); };
        xhr.ontimeout = function () { finish(false); };
        try {
            xhr.send("csrf=" + encodeURIComponent(csrf) + "&event=" + report.event +
                "&position=" + report.position);
        } catch (ignore) { finish(false); }
    }
    function save(event) {
        if (!started || restoring || disabled || !isFinite(video.currentTime)) { return; }
        var ticks = Math.max(0, Math.floor(video.currentTime * 10000000));
        lastSent = new Date().getTime();
        transmit({event: event, position: ticks});
        sentStart = true;
    }
    video.addEventListener("loadedmetadata", restore, false);
    video.addEventListener("durationchange", restore, false);
    video.addEventListener("canplay", restore, false);
    video.addEventListener("seeked", function () {
        if (restoring && Math.abs(video.currentTime - target) <= 2) { restoring = false; }
    }, false);
    video.addEventListener("playing", function () {
        started = true;
        restore();
        save("start");
    }, false);
    video.addEventListener("timeupdate", function () {
        if (!started) { return; }
        restore();
        if (!sentStart) { save("start"); }
        else if (!video.paused && new Date().getTime() - lastSent >= 10000) { save("progress"); }
    }, false);
    video.addEventListener("pause", function () { if (!video.ended) { save("pause"); } }, false);
    video.addEventListener("ended", function () { save("ended"); }, false);
    window.addEventListener("pagehide", function () { if (!video.ended) { save("stop"); } }, false);
}());
