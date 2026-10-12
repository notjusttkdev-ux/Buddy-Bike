/* Buddy Bike Chatbot — ฝั่งหน้าเว็บ
 *
 * สถานะที่หน้าจอแสดง (Week 6): หน้าจอเริ่มต้น / กำลังคิด / ล็อกช่องพิมพ์ / แถบแจ้งปัญหา
 * ภาพน้องบัดดี้และไอคอนทั้งหมดวาดไว้ใน index.html แล้วเรียกใช้ด้วย <use href="#ชื่อ">
 * ความปลอดภัย (Week 11): ข้อความทุกชิ้นใส่ลงหน้าเว็บด้วย textContent ไม่ใช้ innerHTML
 *   คำตอบจาก AI หรือข้อความที่อ่านจากสลิปจึงรันสคริปต์หรือแทรก HTML ไม่ได้
 */
(function () {
  "use strict";

  const MAX_CHARS = Number(document.body.dataset.maxChars) || 500;
  const MAX_IMAGE_MB = Number(document.body.dataset.maxImageMb) || 5;
  const ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp"];
  const CLIENT_TIMEOUT_MS = 100000;

  const $ = (id) => document.getElementById(id);
  const thread = $("thread");
  const hello = $("hello");
  const form = $("composer");
  const input = $("message");
  const sendBtn = $("send-btn");
  const attachBtn = $("attach-btn");
  const fileInput = $("file-input");
  const notice = $("notice");
  const noticeTitle = $("notice-title");
  const noticeBody = $("notice-body");
  const noticeRetry = $("notice-retry");
  const preview = $("attach-preview");
  const thumb = $("attach-thumb");
  const attachName = $("attach-name");
  const counter = $("counter");
  const statusDot = $("status-dot");
  const statusText = $("status-text");
  const dropVeil = $("drop-veil");

  let busy = false;
  let controller = null;     // ใช้ยกเลิกคำขอเมื่อกด "หยุด" หรือรอนานเกินไป
  let stoppedByUser = false;
  let attached = null;       // ไฟล์รูปที่แนบอยู่
  let lastPayload = null;    // เก็บไว้ให้ปุ่ม "ส่งอีกครั้ง"
  let slowTimer = null;

  // ---------- ตัวช่วยสร้าง element ----------
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* แสดงข้อความ: รองรับย่อหน้า รายการที่ขึ้นต้นด้วย "-" และตัวหนา **...** โดยสร้างเป็น DOM node ทั้งหมด */
  function renderText(container, text, skipBullets) {
    let list = null;
    String(text || "").split(/\r?\n/).forEach((raw) => {
      const line = raw.trim();
      if (!line) { list = null; return; }
      const bullet = line.match(/^[-•*]\s+(.*)$/);
      if (bullet) {
        if (skipBullets) return;
        if (!list) { list = el("ul"); container.appendChild(list); }
        inline(list.appendChild(el("li")), bullet[1]);
      } else {
        list = null;
        inline(container.appendChild(el("p")), line);
      }
    });
  }
  function inline(node, text) {
    text.split(/(\*\*[^*]+\*\*)/).forEach((part) => {
      if (!part) return;
      if (part.length > 4 && part.startsWith("**") && part.endsWith("**")) {
        node.appendChild(el("strong", "", part.slice(2, -2)));
      } else {
        node.appendChild(document.createTextNode(part));
      }
    });
  }
  function toBottom() { thread.scrollTop = thread.scrollHeight; }

  /* ดึงภาพวาดจากคลังใน index.html มาใช้ เช่น art("buddy-face", "0 0 120 120") */
  const SVG_NS = "http://www.w3.org/2000/svg";
  function art(id, viewBox) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", viewBox);
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", "#" + id);
    svg.appendChild(use);
    return svg;
  }
  function avatar() {
    const node = el("span", "avatar");
    node.setAttribute("aria-hidden", "true");
    node.appendChild(art("buddy-face", "0 0 120 120"));
    return node;
  }
  function clock() {
    return new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  // ---------- แถบแจ้งปัญหา ----------
  function showNotice(title, body, canRetry) {
    noticeTitle.textContent = title;
    noticeBody.textContent = body;
    noticeRetry.hidden = !(canRetry && lastPayload);
    notice.hidden = false;
    setStatus();
  }
  function hideNotice() { notice.hidden = true; setStatus(); }

  function setStatus() {
    if (busy) {
      statusDot.className = "status-dot busy";
      statusText.textContent = lastPayload && lastPayload.file ? "กำลังอ่านสลิป" : "กำลังหาคำตอบ";
    } else if (!navigator.onLine) {
      statusDot.className = "status-dot down";
      statusText.textContent = "ไม่มีการเชื่อมต่ออินเทอร์เน็ต";
    } else if (!notice.hidden) {
      statusDot.className = "status-dot down";
      statusText.textContent = "มีปัญหา ดูรายละเอียดด้านล่าง";
    } else {
      statusDot.className = "status-dot";
      statusText.textContent = "ออนไลน์ พร้อมตอบคำถาม";
    }
  }

  function setBusy(state) {
    busy = state;
    input.disabled = state;
    attachBtn.disabled = state;
    document.querySelectorAll(".starter, #reset-btn, #reset-btn-mobile").forEach((b) => { b.disabled = state; });
    const label = state ? "หยุดรอคำตอบ" : "ส่งข้อความ";   // ปุ่มเดียวกันสลับไอคอนส่งกับหยุด
    sendBtn.setAttribute("aria-label", label);
    sendBtn.title = label;
    sendBtn.classList.toggle("stop", state);
    setStatus();
    if (!state) input.focus();
  }

  // ---------- ข้อความในห้องแชต ----------
  function addMine(text, file) {
    if (hello.parentNode) hello.remove();
    const wrap = el("div", "msg me");
    const bubble = el("div", "bubble");
    if (file) {
      const img = el("img", "sent");
      img.alt = "รูปที่ส่ง";
      img.src = URL.createObjectURL(file);
      img.addEventListener("load", toBottom);
      bubble.appendChild(img);
    }
    if (text) bubble.appendChild(el("p", "", text));
    wrap.appendChild(bubble);
    wrap.appendChild(el("div", "meta", clock()));
    thread.appendChild(wrap);
    toBottom();
  }

  function addThinking(isSlip) {
    const wrap = el("div", "msg bot");
    const bubble = el("div", "bubble thinking");
    const ride = el("div", "ride");
    ride.append(art("buddy-ride", "0 -12 200 162"), el("i"));
    const text = el("div", "thinking-text");
    const line = el("span", "", isSlip ? "กำลังอ่านสลิป" : "กำลังหาคำตอบจากข้อมูลร้าน");
    const dots = el("span", "dots");
    dots.append(el("i"), el("i"), el("i"));
    line.appendChild(dots);
    text.appendChild(line);
    const hint = el("small", "", "");
    text.appendChild(hint);
    bubble.append(ride, text);
    wrap.append(avatar(), bubble);
    thread.appendChild(wrap);
    toBottom();
    slowTimer = setTimeout(() => { hint.textContent = "ใช้เวลานานกว่าปกติเล็กน้อย กรุณารอสักครู่"; }, 9000);
    return wrap;
  }

  function slipCard(data) {
    const card = el("div", "slip");
    const head = el("div", "slip-head");
    head.append(el("strong", "", "สลิปที่ได้รับ"), el("span", "pill", data.status || "รอเจ้าหน้าที่ตรวจสอบ"));
    card.appendChild(head);
    const row = (label, value, extra) => {
      const r = el("div", "slip-row" + (extra ? " " + extra : ""));
      r.append(el("span", "", label), el("span", "", value));
      card.appendChild(r);
    };
    const amount = typeof data.amount === "number"
      ? data.amount.toLocaleString("th-TH", { minimumFractionDigits: 2 }) + " บาท" : "อ่านไม่ได้";
    row("ชื่อผู้โอน", data.sender_name || "อ่านไม่ได้");
    row("ยอดเงิน", amount, "amount");
    // ระบบเก็บวันที่เป็น ค.ศ. แต่แสดงให้ลูกค้าเป็น พ.ศ. ตามที่เห็นในสลิปไทย
    const parts = String(data.transfer_date || "").split("/");
    const thaiDate = parts.length === 3 ? parts[0] + "/" + parts[1] + "/" + (Number(parts[2]) + 543) : "อ่านไม่ได้";
    row("วันที่โอน (พ.ศ.)", thaiDate);
    if (data.transfer_time) row("เวลาโอน", data.transfer_time + " น.");
    return card;
  }

  function addBot(data) {
    const guarded = data.type === "blocked" || data.type === "slip_rejected";
    const wrap = el("div", "msg bot" + (guarded ? " guarded" : ""));
    const bubble = el("div", "bubble");

    if (data.type === "slip" && data.slip) {
      const lines = String(data.reply || "").split(/\r?\n/);
      bubble.appendChild(el("p", "", lines[0] || "ได้รับสลิปแล้วครับ"));
      bubble.appendChild(slipCard(data.slip));
      renderText(bubble, lines.slice(1).join("\n"), true);
    } else {
      renderText(bubble, data.reply);
    }
    const col = el("div", "col");
    col.appendChild(bubble);

    const meta = el("div", "meta");
    meta.appendChild(el("span", "", clock()));
    if (data.type === "blocked") meta.appendChild(el("span", "shield", "ระบบความปลอดภัยของร้าน"));
    if (data.type === "slip_rejected") meta.appendChild(el("span", "shield", "ยังไม่ได้บันทึกสลิป"));
    (data.sources || []).forEach((s) => {
      const ref = el("span", "ref", s.id);
      ref.title = s.title;
      meta.appendChild(ref);
    });
    if (typeof data.elapsed_ms === "number") {
      meta.appendChild(el("span", "", "ตอบใน " + (data.elapsed_ms / 1000).toFixed(1) + " วินาที"));
    }
    col.appendChild(meta);
    wrap.append(avatar(), col);
    thread.appendChild(wrap);
    toBottom();
  }

  function addNote(text) {
    thread.appendChild(el("div", "note", text));
    toBottom();
  }

  // ---------- แนบรูป ----------
  function clearAttachment() {
    attached = null;
    fileInput.value = "";
    preview.hidden = true;
    if (thumb.src) URL.revokeObjectURL(thumb.src);
    thumb.removeAttribute("src");
  }

  function attachFile(file) {
    if (!file || busy) return;
    if (!ALLOWED_TYPES.includes(file.type)) {
      showNotice("ไฟล์นี้ไม่ใช่รูปที่รองรับ", "เลือกรูปสลิปเป็นไฟล์ JPG, PNG หรือ WEBP แล้วแนบใหม่อีกครั้ง", false);
      fileInput.value = "";
      return;
    }
    if (file.size > MAX_IMAGE_MB * 1024 * 1024) {
      showNotice("รูปใหญ่เกิน " + MAX_IMAGE_MB + " MB",
        "รูปนี้มีขนาด " + (file.size / 1048576).toFixed(1) + " MB ลองบันทึกภาพหน้าจอสลิปแทนไฟล์ต้นฉบับ แล้วแนบใหม่", false);
      fileInput.value = "";
      return;
    }
    if (file.size === 0) {
      showNotice("ไฟล์รูปว่างเปล่า", "เลือกรูปสลิปใหม่อีกครั้ง", false);
      fileInput.value = "";
      return;
    }
    hideNotice();
    attached = file;
    thumb.src = URL.createObjectURL(file);
    attachName.textContent = file.name + " (" + (file.size / 1048576).toFixed(2) + " MB)";
    preview.hidden = false;
    input.focus();
  }

  thumb.addEventListener("error", () => {
    if (!attached) return;
    clearAttachment();
    showNotice("เปิดรูปนี้ไม่ได้", "ไฟล์อาจเสียหาย ลองบันทึกรูปสลิปใหม่แล้วแนบอีกครั้ง", false);
  });

  // ---------- ส่งข้อความ ----------
  async function send(payload, isRetry) {
    if (busy) return;
    if (!navigator.onLine) {
      showNotice("ไม่มีการเชื่อมต่ออินเทอร์เน็ต", "ตรวจสอบ Wi-Fi หรือเน็ตมือถือ แล้วกดส่งอีกครั้ง", true);
      return;
    }
    lastPayload = payload;
    hideNotice();
    if (!isRetry) addMine(payload.message, payload.file);

    const body = new FormData();
    body.append("message", payload.message);
    if (payload.file) body.append("image", payload.file);

    setBusy(true);
    const thinking = addThinking(Boolean(payload.file));
    controller = new AbortController();
    stoppedByUser = false;
    const timeout = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);

    try {
      const response = await fetch("/api/chat", { method: "POST", body, signal: controller.signal });
      let data = null;
      try { data = await response.json(); } catch (_) { /* เซิร์ฟเวอร์ไม่ได้ตอบเป็น JSON */ }

      if (!response.ok) {
        const serverMessage = data && (data.message || (typeof data.detail === "string" ? data.detail : ""));
        const s = response.status;
        const title =
          s === 429 ? "ส่งข้อความถี่เกินไป" :
          s === 413 ? "รูปใหญ่เกินไป" :
          s === 415 ? "ไฟล์นี้ไม่ใช่รูปที่รองรับ" :
          s === 400 || s === 422 ? "ข้อความยังส่งไม่ได้" :
          s === 503 ? "ระบบยังไม่พร้อมตอบ" :
          s === 504 ? "ระบบใช้เวลาตอบนานเกินไป" :
          s >= 500 ? "ระบบของร้านขัดข้องชั่วคราว" : "ส่งข้อความไม่สำเร็จ";
        const fallback = s >= 500 ? "ลองส่งอีกครั้งในอีกสักครู่ หรือติดต่อเจ้าหน้าที่ของร้านโดยตรง"
                                  : "ตรวจสอบข้อความหรือรูปที่แนบ แล้วลองใหม่อีกครั้ง";
        showNotice(title, serverMessage || fallback, s === 429 || s >= 500);
        return;
      }
      if (!data || typeof data.reply !== "string") {
        showNotice("ระบบตอบกลับไม่สมบูรณ์", "ลองส่งอีกครั้ง ถ้ายังไม่ได้ กรุณาติดต่อเจ้าหน้าที่ของร้าน", true);
        return;
      }
      lastPayload = null;
      addBot(data);
    } catch (err) {
      if (err.name === "AbortError" && stoppedByUser) {
        addNote("หยุดรอคำตอบแล้ว พิมพ์คำถามใหม่ได้เลยครับ");
        lastPayload = null;
      } else if (err.name === "AbortError") {
        showNotice("ระบบใช้เวลาตอบนานเกินไป", "อาจมีผู้ใช้งานจำนวนมาก ลองส่งอีกครั้งในอีกสักครู่", true);
      } else if (!navigator.onLine) {
        showNotice("อินเทอร์เน็ตหลุดระหว่างส่ง", "ตรวจสอบการเชื่อมต่อ แล้วกดส่งอีกครั้ง", true);
      } else {
        showNotice("เชื่อมต่อระบบของร้านไม่ได้", "ลองส่งอีกครั้งในอีกสักครู่ หรือติดต่อเจ้าหน้าที่ของร้านโดยตรง", true);
      }
    } finally {
      clearTimeout(timeout);
      clearTimeout(slowTimer);
      thinking.remove();
      controller = null;
      setBusy(false);
    }
  }

  function submit(text) {
    const message = (text !== undefined ? text : input.value).trim();
    const file = attached;
    if (!message && !file) {
      showNotice("ยังไม่มีข้อความ", "พิมพ์คำถาม หรือกด “แนบสลิป” เพื่อส่งรูปสลิปการโอนเงิน", false);
      input.focus();
      return;
    }
    if (message.length > MAX_CHARS) {
      showNotice("ข้อความยาวเกินไป", "พิมพ์ได้ไม่เกิน " + MAX_CHARS + " ตัวอักษร ลองแบ่งเป็นคำถามสั้น ๆ", false);
      return;
    }
    input.value = "";
    updateCounter();
    autoResize();
    clearAttachment();
    send({ message, file }, false);
  }

  // ---------- ช่องพิมพ์ ----------
  function updateCounter() {
    const n = input.value.length;
    counter.textContent = n + "/" + MAX_CHARS;
    counter.classList.toggle("near", n >= MAX_CHARS * 0.9);
  }
  function autoResize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 140) + "px";
  }

  async function resetChat() {
    if (busy) return;
    try { await fetch("/api/reset", { method: "POST" }); } catch (_) { /* ล้างหน้าจอต่อได้แม้เซิร์ฟเวอร์ไม่ตอบ */ }
    thread.replaceChildren(hello);
    clearAttachment();
    lastPayload = null;
    hideNotice();
    input.value = "";
    updateCounter();
    autoResize();
    input.focus();
  }

  // ---------- Event ----------
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy) {                       // ปุ่มเดียวกันทำหน้าที่ "หยุด"
      stoppedByUser = true;
      if (controller) controller.abort();
      return;
    }
    submit();
  });
  input.addEventListener("input", () => { updateCounter(); autoResize(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  input.addEventListener("paste", (e) => {
    const file = Array.from((e.clipboardData && e.clipboardData.files) || []).find((f) => f.type.startsWith("image/"));
    if (file) { e.preventDefault(); attachFile(file); }
  });

  document.querySelectorAll(".starter").forEach((b) => b.addEventListener("click", () => submit(b.dataset.q)));
  attachBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => attachFile(fileInput.files[0]));
  $("attach-remove").addEventListener("click", clearAttachment);
  $("notice-close").addEventListener("click", hideNotice);
  noticeRetry.addEventListener("click", () => { if (lastPayload) send(lastPayload, true); });
  $("reset-btn").addEventListener("click", resetChat);
  $("reset-btn-mobile").addEventListener("click", resetChat);

  // เมนูข้อมูลร้านบนจอแคบ (บนจอกว้างโปสเตอร์แสดงอยู่ตลอด)
  const menuBtn = $("menu-btn");
  const scrim = $("scrim");
  function setMenu(open) {
    document.body.classList.toggle("menu-open", open);
    scrim.hidden = !open;
    menuBtn.setAttribute("aria-expanded", String(open));
    if (open) $("menu-close").focus(); else if (document.activeElement === $("menu-close")) menuBtn.focus();
  }
  menuBtn.addEventListener("click", () => setMenu(true));
  $("menu-close").addEventListener("click", () => setMenu(false));
  scrim.addEventListener("click", () => setMenu(false));
  $("reset-btn").addEventListener("click", () => setMenu(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") setMenu(false); });

  // ลากรูปมาวางในห้องแชต
  let dragDepth = 0;
  const stage = document.querySelector(".stage");
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  stage.addEventListener("dragenter", (e) => { if (hasFiles(e)) { e.preventDefault(); dragDepth += 1; dropVeil.hidden = false; } });
  stage.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  stage.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) dropVeil.hidden = true; });
  stage.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    dragDepth = 0;
    dropVeil.hidden = true;
    attachFile(e.dataTransfer.files[0]);
  });

  window.addEventListener("online", setStatus);
  window.addEventListener("offline", () => {
    setStatus();
    if (!busy) showNotice("ไม่มีการเชื่อมต่ออินเทอร์เน็ต", "ข้อความจะส่งได้อีกครั้งเมื่อกลับมาออนไลน์", false);
  });

  updateCounter();
  setStatus();
  input.focus();
})();
