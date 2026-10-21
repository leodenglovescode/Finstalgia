const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
function boot(resume) {
    const videoEvents = {}, windowEvents = {}, requests = [];
    const status = {};
    let now = 1000;
    const video = {currentTime: 0, readyState: 0, paused: true, ended: false,
        getAttribute: function (key) {return {"data-report": "/playback/opaque", "data-csrf": "csrf+token",
            "data-resume": String(resume)}[key];},
        addEventListener: function (key, fn) {videoEvents[key] = fn;}};
    function XHR() {this.status = 204; this.readyState = 4;}
    XHR.prototype.open = function (method, url, async) {
        assert.equal(method, "POST"); assert.equal(url, "/playback/opaque"); assert.equal(async, true);
    };
    XHR.prototype.setRequestHeader = function () {};
    XHR.prototype.send = function (body) {
        requests.push(Object.fromEntries(new URLSearchParams(body)));
        this.onreadystatechange();
    };
    const context = {document: {getElementById: function (id) {return id === "player" ? video : status;}},
        window: {XMLHttpRequest: XHR, addEventListener: function (key, fn) {windowEvents[key] = fn;}},
        XMLHttpRequest: XHR, Date: function () {this.getTime = function () {return now;};}};
    vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), context);
    return {video, videoEvents, windowEvents, requests, status, advance: function () {now += 11000;}};
}
const p = boot(7200000000);
assert.equal(p.requests.length, 0);
p.videoEvents.timeupdate(); // Loading metadata cannot erase the saved position.
assert.equal(p.requests.length, 0);
p.video.readyState = 1;
p.videoEvents.loadedmetadata();
assert.equal(p.video.currentTime, 720);
p.video.paused = false;
p.videoEvents.playing();
assert.equal(p.requests[0].position, "7200000000");
assert.equal(p.requests[0].csrf, "csrf+token");
p.video.currentTime = 731;
p.advance(); p.videoEvents.timeupdate();
assert.equal(p.requests[1].event, "progress");
assert.equal(p.requests[1].position, "7310000000");
p.video.paused = true; p.videoEvents.pause();
assert.equal(p.requests[2].event, "pause");
p.video.ended = true; p.video.currentTime = 5400; p.videoEvents.ended();
assert.equal(p.requests[3].event, "ended");
assert.equal(p.requests[3].position, "54000000000");
p.windowEvents.pagehide();
assert.equal(p.requests.length, 4);
const fresh = boot(0);
fresh.video.readyState = 1; fresh.videoEvents.loadedmetadata();
assert.equal(fresh.video.currentTime, 0);
console.log("Native video events: resume, progress, pause, ended and no pre-play writes passed.");
