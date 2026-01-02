import React, {
  useEffect,
  useMemo,
  useRef,
  useState,
  useCallback,
} from "react";

// Simple mobile detection
function isMobileDevice() {
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
    navigator.userAgent
  );
}

// Simple wake lock helper
async function requestWakeLock() {
  if ("wakeLock" in navigator) {
    try {
      return await navigator.wakeLock.request("screen");
    } catch (e) {
      console.log("Wake lock not available:", e);
      return null;
    }
  }
  return null;
}

async function releaseWakeLock(lock) {
  if (lock) {
    try {
      await lock.release();
    } catch (e) {
      // Ignore
    }
  }
}

function cn(...parts) {
  return parts.filter(Boolean).join(" ");
}

// Lightweight inline SVG icons (no external dependencies)
const Icons = {
  pdf: (
    <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2l5 5h-5V4zM9 13h2v5H9v-5zm4 0h2v5h-2v-5z" />
    </svg>
  ),
  bolt: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z" />
    </svg>
  ),
  robot: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2zM7.5 13a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zm9 0a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3zM9 18h6v1H9v-1z" />
    </svg>
  ),
  shield: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
    </svg>
  ),
  copy: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z" />
    </svg>
  ),
  spinner: (
    <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  ),
  circle: (
    <svg className="w-2 h-2" fill="currentColor" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" />
    </svg>
  ),
  check: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z" />
    </svg>
  ),
  folder: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z" />
    </svg>
  ),
  file: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm4 18H6V4h7v5h5v11z" />
    </svg>
  ),
  play: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M8 5v14l11-7z" />
    </svg>
  ),
  download: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z" />
    </svg>
  ),
  clock: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm.5-13H11v6l5.2 3.2.8-1.3-4.5-2.7V7z" />
    </svg>
  ),
  lightbulb: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M9 21c0 .5.4 1 1 1h4c.6 0 1-.5 1-1v-1H9v1zm3-19C8.1 2 5 5.1 5 9c0 2.4 1.2 4.5 3 5.7V17c0 .5.4 1 1 1h6c.6 0 1-.5 1-1v-2.3c1.8-1.3 3-3.4 3-5.7 0-3.9-3.1-7-7-7z" />
    </svg>
  ),
  wand: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M7.5 5.6L10 7 8.6 4.5 10 2 7.5 3.4 5 2l1.4 2.5L5 7l2.5-1.4zm12 9.8L17 14l1.4 2.5L17 19l2.5-1.4L22 19l-1.4-2.5L22 14l-2.5 1.4zM22 2l-2.5 1.4L17 2l1.4 2.5L17 7l2.5-1.4L22 7l-1.4-2.5L22 2zM9.4 10.6L2 18l4 4 7.4-7.4-4-4zm-1.4 7L6.6 19 5 17.4l1.4-1.4 1.6 1.6z" />
    </svg>
  ),
  arrow: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M10 17l5-5-5-5v10z" />
    </svg>
  ),
  signal: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M2 22h2V12H2v10zm4 0h2V9H6v13zm4 0h2V6h-2v16zm4 0h2V2h-2v20zm4 0h2v-8h-2v8z" />
    </svg>
  ),
  export: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M19 12v7H5v-7H3v7c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2v-7h-2zm-6 .67l2.59-2.58L17 11.5l-5 5-5-5 1.41-1.41L11 12.67V3h2v9.67z" />
    </svg>
  ),
  stop: (
    <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
      <path d="M6 6h12v12H6z" />
    </svg>
  ),
  clipboard: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M19 3h-4.18C14.4 1.84 13.3 1 12 1s-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 0c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm7 16H5V5h2v2h10V5h2v14z" />
    </svg>
  ),
  minus: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M19 13H5v-2h14v2z" />
    </svg>
  ),
  error: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z" />
    </svg>
  ),
  question: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8c0-2.21 1.79-4 4-4s4 1.79 4 4c0 .88-.36 1.68-.93 2.25z" />
    </svg>
  ),
  checkCircle: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
    </svg>
  ),
  upload: (
    <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
      <path d="M9 16h6v-6h4l-7-7-7 7h4zm-4 2h14v2H5z" />
    </svg>
  ),
  cog: (
    <svg
      className="w-4 h-4 animate-spin"
      fill="currentColor"
      viewBox="0 0 24 24"
    >
      <path d="M12 15.5A3.5 3.5 0 0 1 8.5 12 3.5 3.5 0 0 1 12 8.5a3.5 3.5 0 0 1 3.5 3.5 3.5 3.5 0 0 1-3.5 3.5m7.43-2.53c.04-.32.07-.64.07-.97 0-.33-.03-.66-.07-1l2.11-1.63c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.31-.61-.22l-2.49 1c-.52-.39-1.06-.73-1.69-.98l-.37-2.65A.506.506 0 0 0 14 2h-4c-.25 0-.46.18-.5.42l-.37 2.65c-.63.25-1.17.59-1.69.98l-2.49-1c-.22-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64L4.57 11c-.04.34-.07.67-.07 1 0 .33.03.65.07.97l-2.11 1.66c-.19.15-.25.42-.12.64l2 3.46c.12.22.39.3.61.22l2.49-1.01c.52.4 1.06.74 1.69.99l.37 2.65c.04.24.25.42.5.42h4c.25 0 .46-.18.5-.42l.37-2.65c.63-.26 1.17-.59 1.69-.99l2.49 1.01c.22.08.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.66z" />
    </svg>
  ),
};

function makeId() {
  return `${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function getOrCreateSessionId() {
  try {
    const key = "ordermypdf_session_id";
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const id = `sess_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    window.localStorage.setItem(key, id);
    return id;
  } catch {
    return `sess_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  }
}

// Job persistence helpers for recovery after page refresh/close
const JOB_STORAGE_KEY = "ordermypdf_pending_job";

function savePendingJob(jobId, prompt, fileName, estTime) {
  try {
    const data = { jobId, prompt, fileName, estTime, startedAt: Date.now() };
    window.localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(data));
  } catch (e) {
    console.log("Could not save job to localStorage", e);
  }
}

function loadPendingJob() {
  try {
    const raw = window.localStorage.getItem(JOB_STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    // Expire jobs after 30 minutes (same as server)
    if (Date.now() - data.startedAt > 30 * 60 * 1000) {
      clearPendingJob();
      return null;
    }
    return data;
  } catch (e) {
    return null;
  }
}

function clearPendingJob() {
  try {
    window.localStorage.removeItem(JOB_STORAGE_KEY);
  } catch (e) {
    // Ignore
  }
}

function inferDownloadLabel(result) {
  if (!result?.output_file) return "Download";
  const lower = String(result.output_file).toLowerCase();
  if (lower.endsWith(".docx")) return "Download Converted DOCX";

  switch (result.operation) {
    case "merge":
      return "Download Merged PDF";
    case "split":
      return "Download Extracted PDF";
    case "delete":
      return "Download Updated PDF";
    case "compress":
    case "compress_to_target":
      return "Download Compressed PDF";
    case "pdf_to_docx":
      return "Download Converted DOCX";
    case "multi":
      return "Download Result";
    default:
      return "Download Result";
  }
}

// Calculate total file size in MB
function getTotalFileSizeMB(files) {
  if (!files || files.length === 0) return 0;
  return files.reduce((sum, f) => sum + (f.size || 0), 0) / (1024 * 1024);
}

// Estimate wait time based on file size and operation (processing only, not upload)
function estimateWaitTime(sizeMB, prompt) {
  const lower = (prompt || "").toLowerCase();

  // Base processing time (server-side, after upload completes)
  // These are calibrated based on actual Render server performance
  let baseSeconds;

  // OCR is CPU-intensive
  if (/ocr/i.test(lower)) {
    baseSeconds = 10 + sizeMB * 0.5; // ~10s base + 0.5s per MB
  }
  // PDF to DOCX conversion
  else if (/docx|word/i.test(lower)) {
    baseSeconds = 8 + sizeMB * 0.4;
  }
  // Compression with target
  else if (/compress/i.test(lower)) {
    // Iterative compression is slower for large files
    if (sizeMB > 50) {
      baseSeconds = 15 + sizeMB * 0.3;
    } else {
      baseSeconds = 8 + sizeMB * 0.25;
    }
  }
  // PDF to images
  else if (/png|jpg|jpeg|image/i.test(lower)) {
    baseSeconds = 5 + sizeMB * 0.3;
  }
  // Simple operations (merge, split, rotate, etc.)
  else {
    baseSeconds = 3 + sizeMB * 0.1;
  }

  // Add AI parsing overhead (~2-3 seconds)
  baseSeconds += 3;

  // Round to reasonable display
  const seconds = Math.max(5, Math.round(baseSeconds));

  if (seconds < 60) return `~${seconds}s`;
  if (seconds < 120) return "~1 min";
  const mins = Math.round(seconds / 60);
  return `~${mins} mins`;
}

// Check if prompt has specific compression target
function hasSpecificCompressionTarget(prompt) {
  const lower = (prompt || "").toLowerCase();
  // Specific MB target: "compress to 5mb", "2mb"
  if (/\d+\s*mb/i.test(lower)) return true;
  // Percentage: "by 50%", "compress 30%"
  if (/\d+\s*%/.test(lower)) return true;
  // Fractions: "by half", "quarter", "third"
  if (/\b(half|quarter|third)\b/i.test(lower)) return true;
  // Qualitative with specific intent: "very tiny", "smallest", "maximum"
  if (/\b(very tiny|smallest|maximum|minimal)\b/i.test(lower)) return true;
  return false;
}

// Check if this is a plain compress command without target
function isPlainCompress(prompt) {
  const lower = (prompt || "").toLowerCase().trim();
  // Matches: "compress", "compress it", "compress this", "compress pdf", "compress this pdf"
  return /^compress(\s+(it|this|pdf|this pdf|the pdf))?$/i.test(lower);
}

function looksLikeClarification(msg) {
  if (!msg) return false;
  const s = String(msg).trim();
  if (!s) return false;
  return s.endsWith("?") || /^how\b|^which\b|^what\b|^would you\b/i.test(s);
}

function isNonEmptyArray(v) {
  return Array.isArray(v) && v.length > 0;
}

function normalizeWhitespace(s) {
  return String(s || "")
    .replace(/[\r\n]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeCompressTargetLanguage(text) {
  // UI-only normalization to match backend parsing.
  // Examples:
  // - "by 2mb" -> "to 2mb"
  // - "2 mb" -> "2mb"
  const t = normalizeWhitespace(text);
  return t
    .replace(/\bby\s*(\d+)\s*mb\b/i, "to $1mb")
    .replace(/\bunder\s*(\d+)\s*mb\b/i, "to $1mb")
    .replace(/\b(\d+)\s*mb\b/gi, "$1mb");
}

function levenshtein(a, b) {
  const s = String(a || "");
  const t = String(b || "");
  const m = s.length;
  const n = t.length;
  if (m === 0) return n;
  if (n === 0) return m;

  const prev = new Array(n + 1);
  const curr = new Array(n + 1);
  for (let j = 0; j <= n; j += 1) prev[j] = j;

  for (let i = 1; i <= m; i += 1) {
    curr[0] = i;
    const si = s.charCodeAt(i - 1);
    for (let j = 1; j <= n; j += 1) {
      const cost = si === t.charCodeAt(j - 1) ? 0 : 1;
      curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
    }
    for (let j = 0; j <= n; j += 1) prev[j] = curr[j];
  }
  return prev[n];
}

const OP_KEYWORDS = [
  "compress",
  "merge",
  "split",
  "extract",
  "keep",
  "delete",
  "remove",
  "convert",
  "docx",
  "word",
  "pages",
  "page",
  "then",
  "and",
  "after",
  "before",
  "to",
  "under",
  "mb",
];

function fixCommonTypos(text) {
  const t = normalizeWhitespace(text);
  return t
    .replace(/\bcom+res+s*\b/gi, "compress")
    .replace(/\bcompres+s*\b/gi, "compress")
    .replace(/\bcomprss\b/gi, "compress")
    .replace(/\bspl+it\b/gi, "split")
    .replace(/\bspl+it+\b/gi, "split")
    .replace(/\bmerg(e)?\b/gi, "merge")
    .replace(/\bdel+ete\b/gi, "delete")
    .replace(/\bremvoe\b/gi, "remove")
    .replace(/\bconver+t\b/gi, "convert")
    .replace(/\bdoc\s*x\b/gi, "docx");
}

function normalizePromptForSend(text) {
  // Frontend-only “advanced” typo tolerance.
  // We correct obvious typos for known operation keywords to increase parse success.
  const base = fixCommonTypos(normalizeCompressTargetLanguage(text));

  const threshold = 0.74; // conservative enough for ops, but catches "comres" -> "compress"
  return base.replace(/[A-Za-z]{3,}/g, (word) => {
    const w = word.toLowerCase();
    if (OP_KEYWORDS.includes(w)) return word;
    if (w.length < 4) return word;

    let best = null;
    let bestScore = 0;
    for (const k of OP_KEYWORDS) {
      const dist = levenshtein(w, k);
      const score = 1 - dist / Math.max(w.length, k.length);
      if (score > bestScore) {
        bestScore = score;
        best = k;
      }
    }

    // Extra safety: only correct to actual operation-ish keywords
    if (best && bestScore >= threshold) {
      return best;
    }
    return word;
  });
}

function formatRemainingSeconds(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (!Number.isFinite(s) || s <= 0) return "";
  if (s < 60) return `~${s}s`;
  const mins = Math.floor(s / 60);
  const rem = s % 60;
  if (mins < 60) return rem ? `~${mins}m ${rem}s` : `~${mins}m`;
  const hrs = Math.floor(mins / 60);
  const m2 = mins % 60;
  return m2 ? `~${hrs}h ${m2}m` : `~${hrs}h`;
}

function buildProcessingText(msg, estimatedRemainingSeconds, status) {
  const base = String(msg || "Processing...").trim() || "Processing...";
  const eta = formatRemainingSeconds(estimatedRemainingSeconds);
  if (!eta) {
    if (status === "pending") return `${base} (queueing...)`;
    return base;
  }
  return `${base} (ETA ${eta})`;
}

function inferClarificationKind(question) {
  const q = String(question || "").toLowerCase();
  if (q.includes("rotate") && q.includes("degree")) return "rotate_degrees";
  if (
    q.includes("compress") &&
    (q.includes("mb") || q.includes("size") || q.includes("specific"))
  ) {
    return "compress";
  }
  if (q.includes("keep") && q.includes("pages")) return "keep_pages";
  if (q.includes("delete") && q.includes("pages")) return "delete_pages";
  if (q.includes("which pages")) return "keep_pages";
  if (q.includes("which page")) return "keep_pages";
  return "freeform";
}

function buildClarifiedPrompt({ baseInstruction, question, userReply }) {
  const kind = inferClarificationKind(question);
  const reply = normalizeCompressTargetLanguage(userReply);
  const base = normalizeWhitespace(baseInstruction);

  if (kind === "rotate_degrees") {
    const r = normalizeWhitespace(userReply).toLowerCase();
    // Numeric-only replies are extremely common.
    const num = r.match(/^(-?\d+)\s*(deg|degree|degrees)?$/i);
    if (num) return `rotate ${num[1]} degrees`;
    if (/\bleft\b/.test(r)) return "rotate left";
    if (/\bright\b/.test(r)) return "rotate right";
    if (/\bflip\b/.test(r)) return "rotate 180 degrees";
    // Fall back to combining.
    return normalizeWhitespace(`${base} ${reply}`);
  }

  if (kind === "compress") {
    // If they replied just "2mb" or "to 2mb", generate a clean instruction.
    const mb = reply.match(/\b(\d+)mb\b/i);
    if (mb) return `compress to ${mb[1]}mb`;

    // Qualitative replies: "a little", "very tiny" etc.
    if (
      /\b(little|slight|tiny|smallest|maximum|strong|best quality|minimal compression)\b/i.test(
        reply
      )
    ) {
      return `compress ${reply}`;
    }

    // Percent-based replies: "50%" etc.
    if (/%/.test(reply)) return `compress by ${reply.replace(/[^0-9%]/g, "")}`;

    // Otherwise, combine.
    return normalizeWhitespace(`${base} ${reply}`);
  }

  if (kind === "keep_pages") {
    if (/\bpage\b|\bpages\b/i.test(reply)) return reply;
    return `keep pages ${reply}`;
  }

  if (kind === "delete_pages") {
    if (/\bdelete\b|\bremove\b/i.test(reply)) return reply;
    return `delete pages ${reply}`;
  }

  return normalizeWhitespace(`${base} ${reply}`);
}

function applyHumanDefaults(text) {
  const t = normalizeWhitespace(text);
  const lower = t.toLowerCase();

  // File-type only prompts (very common): execute directly.
  if (/^(png|jpg|jpeg)$/i.test(lower)) return `export pages as ${lower} images`;
  if (/^(docx|word)$/i.test(lower)) return "convert to docx";
  if (/^txt$/i.test(lower)) return "extract text";
  if (/^ocr$/i.test(lower)) return "ocr this";

  // Rotate without degrees: default to 90.
  if (
    /(\brotate\b|\bturn\b|\bmake it straight\b)/i.test(lower) &&
    !/(-?\d+)/.test(lower)
  ) {
    return `${t} 90 degrees`;
  }
  // Common rotate aliases.
  if (/\bflip\b/i.test(lower)) return "rotate 180 degrees";
  if (/\brotate\s+left\b/i.test(lower)) return "rotate -90 degrees";
  if (/\brotate\s+right\b/i.test(lower)) return "rotate 90 degrees";

  return t;
}

export default function App() {
  const fileInputRef = useRef(null);
  const promptRef = useRef(null);
  const chatEndRef = useRef(null);

  const [files, setFiles] = useState([]);
  const [lastFileName, setLastFileName] = useState("");

  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [clarification, setClarification] = useState("");
  const [pendingClarification, setPendingClarification] = useState(null);
  const [messages, setMessages] = useState(() => [
    {
      id: makeId(),
      role: "agent",
      tone: "neutral",
      text: "Upload your files, then tell me what to do — I can merge, split, compress, OCR, convert, and clean up PDFs.",
    },
  ]);

  const sessionIdRef = useRef(getOrCreateSessionId());
  const abortControllerRef = useRef(null);
  const wakeLockRef = useRef(null);

  const [toast, setToast] = useState(null);
  const [downloadBlink, setDownloadBlink] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0); // 0-100 for upload phase
  const [isUploading, setIsUploading] = useState(false); // true during upload, false during processing
  const [processingMessage, setProcessingMessage] = useState("");
  const currentJobIdRef = useRef(null);
  const [lastSubmittedPrompt, setLastSubmittedPrompt] = useState("");
  const [fileAttention, setFileAttention] = useState(false);
  const [ramStats, setRamStats] = useState(null);

  // Track uploaded files to avoid re-uploading
  const [uploadedFileNames, setUploadedFileNames] = useState([]); // file names on server
  const [lastUploadedFiles, setLastUploadedFiles] = useState([]); // File objects that were uploaded

  const statusPhrases = useMemo(
    () => [
      "🤖 Analyzing your request…",
      "📄 Preparing PDF operations…",
      "⚙️ Processing files securely…",
      "🧠 Planning steps…",
      "✨ Finalizing output…",
    ],
    []
  );

  const promptSuggestions = useMemo(
    () => [
      "compress to 5MB",
      "merge all PDFs",
      "delete pages 3-5",
      "convert to Word",
      "convert this DOCX to PDF",
      "extract first 10 pages",
      "rotate all pages 90°",
      "OCR this scanned doc",
      "remove blank pages",
      "remove duplicate pages",
      "enhance scan (make it clearer)",
      "flatten PDF",
      "add page numbers",
      "export as PNG images",
      "compress then split page 1",
      "watermark DRAFT on all",
      "JPG to PDF",
    ],
    []
  );

  const [statusIndex, setStatusIndex] = useState(0);
  const [recoveredJob, setRecoveredJob] = useState(null);

  // Fetch RAM stats on mount and periodically
  useEffect(() => {
    let interval = null;
    let retryCount = 0;
    const maxRetries = 3;

    const fetchRam = async () => {
      try {
        const res = await fetch("/api/ram");
        if (res.ok) {
          const data = await res.json();
          console.log("[RAM] Fetched:", data);
          // Only set if we got useful data
          if (data && (data.rss_mb || data.peak_rss_mb || data.level)) {
            setRamStats(data);
            retryCount = 0; // Reset retry count on success
          } else {
            console.warn("[RAM] Got empty/incomplete data:", data);
            // Retry a few times on initial load
            if (retryCount < maxRetries) {
              retryCount++;
              setTimeout(fetchRam, 2000);
            }
          }
        } else {
          console.warn("[RAM] Non-OK response:", res.status);
        }
      } catch (e) {
        console.warn("[RAM] Failed to fetch:", e);
        // Retry on error during initial load
        if (retryCount < maxRetries) {
          retryCount++;
          setTimeout(fetchRam, 2000);
        }
      }
    };

    // Initial fetch with slight delay to let backend warm up
    setTimeout(fetchRam, 500);

    // Poll every 15 seconds (always, not just when idle)
    interval = setInterval(fetchRam, 15000);

    return () => {
      if (interval) clearInterval(interval);
    };
  }, []); // Remove loading dependency so it always polls

  // Check for pending job on mount (recovery after page refresh)
  useEffect(() => {
    const pending = loadPendingJob();
    if (!pending) return;

    setRecoveredJob(pending);

    // Show recovery message
    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: "agent",
        tone: "neutral",
        text: `🔄 Found a pending job from earlier. Checking status...`,
      },
    ]);

    // Resume polling for this job
    resumePendingJob(pending);
  }, []);

  // Resume polling for a recovered job
  const resumePendingJob = async (pending) => {
    const { jobId, prompt, fileName } = pending;

    setLoading(true);
    setIsUploading(false);
    setProcessingMessage("Checking job status...");
    currentJobIdRef.current = jobId;
    abortControllerRef.current = new AbortController();

    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: "agent",
        tone: "status",
        text: `Resuming: ${prompt || fileName}...`,
      },
    ]);

    try {
      let completed = false;
      let pollCount = 0;
      const maxPolls = 600; // 10 minutes at 1 second intervals

      while (!completed && pollCount < maxPolls) {
        if (abortControllerRef.current?.signal.aborted) {
          throw new DOMException("Cancelled", "AbortError");
        }

        await new Promise((resolve) => setTimeout(resolve, 1000)); // Poll every 1 second
        pollCount++;

        const statusRes = await fetch(`/job/${jobId}/status`, {
          signal: abortControllerRef.current?.signal,
        });

        if (statusRes.status === 404) {
          // Job expired or doesn't exist
          clearPendingJob();
          setLoading(false);
          setRecoveredJob(null);
          setMessages((prev) => {
            const trimmed = prev.filter((m) => m.tone !== "status");
            return [
              ...trimmed,
              {
                id: makeId(),
                role: "agent",
                tone: "neutral",
                text: "Previous job expired. Please upload your file and try again.",
              },
            ];
          });
          return;
        }

        if (!statusRes.ok) {
          throw new Error(`Status check failed: ${statusRes.status}`);
        }

        const statusData = await statusRes.json();
        const msg = statusData.message || "Processing...";

        updateRamFromStatus(statusData);
        const statusText = buildProcessingText(
          msg,
          statusData.estimated_remaining,
          statusData.status
        );
        setProcessingMessage(statusText);
        if (statusData.ram) {
          console.log("[RAM DEBUG] Status RAM data:", statusData.ram);
          setRamStats(statusData.ram);
        } else {
          console.warn("[RAM DEBUG] No ram field in statusData");
          // Don't clear ramStats here - periodic fetch will update it
        }

        setMessages((prev) => {
          const trimmed = prev.filter((m) => m.tone !== "status");
          return [
            ...trimmed,
            {
              id: makeId(),
              role: "agent",
              tone: "status",
              text: statusText,
            },
          ];
        });

        if (
          statusData.status === "completed" ||
          statusData.status === "failed"
        ) {
          completed = true;
          currentJobIdRef.current = null;
          clearPendingJob();
          setRecoveredJob(null);

          setMessages((prev) => prev.filter((m) => m.tone !== "status"));

          const resultData = statusData.result;

          if (resultData?.status === "success") {
            setResult({
              status: "success",
              output_file: resultData.output_file,
              message: resultData.message,
              operation: resultData.operation,
            });
            setProcessingMessage("Complete!");
            setDownloadBlink(true);
            setTimeout(() => setDownloadBlink(false), 1600);
            setMessages((prev) => [
              ...prev,
              {
                id: makeId(),
                role: "agent",
                tone: "success",
                text: resultData.message || "Done! Your file is ready.",
              },
            ]);
          } else {
            const msg = resultData?.message || "Processing failed";
            setError(msg);
            setMessages((prev) => [
              ...prev,
              { id: makeId(), role: "agent", tone: "error", text: msg },
            ]);
          }
        } else if (statusData.status === "cancelled") {
          completed = true;
          currentJobIdRef.current = null;
          clearPendingJob();
          setRecoveredJob(null);
        }
      }

      if (!completed) {
        clearPendingJob();
        throw new Error("Job timed out.");
      }
    } catch (err) {
      currentJobIdRef.current = null;
      setProcessingMessage("");
      clearPendingJob();
      setRecoveredJob(null);

      if (err?.name !== "AbortError") {
        const msg = `Failed to resume job: ${err?.message || err}`;
        setError(msg);
        setMessages((prev) => {
          const trimmed = prev.filter((m) => m.tone !== "status");
          return [
            ...trimmed,
            { id: makeId(), role: "agent", tone: "error", text: msg },
          ];
        });
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Subtle cursor glow for "premium" depth.
    let raf = 0;
    const onMove = (e) => {
      const x = e?.clientX ?? 0;
      const y = e?.clientY ?? 0;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const root = document.documentElement;
        root.style.setProperty("--mx", `${x}px`);
        root.style.setProperty("--my", `${y}px`);
      });
    };

    window.addEventListener("mousemove", onMove, { passive: true });
    return () => {
      window.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  useEffect(() => {
    if (!loading) return;
    const t = setInterval(
      () => setStatusIndex((i) => (i + 1) % statusPhrases.length),
      2200
    );
    return () => clearInterval(t);
  }, [loading, statusPhrases.length]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading, result, error, clarification]);

  // Wake Lock: Keep screen awake during processing (mobile)
  useEffect(() => {
    const requestWakeLock = async () => {
      if (loading && "wakeLock" in navigator) {
        try {
          wakeLockRef.current = await navigator.wakeLock.request("screen");
        } catch (err) {
          // Wake lock request failed - not critical
          console.log("Wake lock not available:", err);
        }
      }
    };

    const releaseWakeLock = async () => {
      if (wakeLockRef.current) {
        try {
          await wakeLockRef.current.release();
          wakeLockRef.current = null;
        } catch (err) {
          // Ignore release errors
        }
      }
    };

    if (loading) {
      requestWakeLock();
    } else {
      releaseWakeLock();
    }

    return () => {
      releaseWakeLock();
    };
  }, [loading]);

  // Warn user if they try to leave/switch tabs during processing
  useEffect(() => {
    if (!loading) return;

    const handleVisibilityChange = () => {
      if (document.hidden && loading) {
        // Can't show toast when hidden, but we can set a flag
        // Toast will show when they return
      }
    };

    const handleBeforeUnload = (e) => {
      if (loading) {
        e.preventDefault();
        e.returnValue =
          "Processing is in progress. Are you sure you want to leave?";
        return e.returnValue;
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [loading]);

  // Check if current files match the last uploaded files
  const canReuseFiles = useCallback(() => {
    if (!uploadedFileNames.length || !lastUploadedFiles.length) return false;
    if (files.length !== lastUploadedFiles.length) return false;

    // Check if all files match by name and size
    return files.every(
      (f, i) =>
        lastUploadedFiles[i] &&
        f.name === lastUploadedFiles[i].name &&
        f.size === lastUploadedFiles[i].size
    );
  }, [files, uploadedFileNames, lastUploadedFiles]);

  // Handle file selection
  const handleFileChange = (e) => {
    const incoming = Array.from(e.target.files || []);

    // Allow re-selecting the same file(s) later.
    try {
      e.target.value = "";
    } catch {
      // ignore
    }

    if (!incoming.length) return;

    // Deduplicate by name+size to avoid accidental duplicates.
    const keyOf = (f) => `${f?.name || ""}::${f?.size || 0}`;
    const existingKeys = new Set(files.map(keyOf));
    const dedupedIncoming = incoming.filter((f) => !existingKeys.has(keyOf(f)));

    // Enforce max file count (25)
    const MAX_FILES = 25;
    const room = Math.max(0, MAX_FILES - files.length);
    let accepted = dedupedIncoming;
    if (dedupedIncoming.length > room) {
      accepted = dedupedIncoming.slice(0, room);
      showToast("At once only 25 files allowed.", 4500);
    }

    // If no room, keep state unchanged.
    if (!accepted.length) return;

    const next = files.concat(accepted);
    setFiles(next);
    setLastFileName(accepted[accepted.length - 1].name);

    // Check if these are different files - reset uploaded state
    const filesChanged =
      next.length !== lastUploadedFiles.length ||
      next.some(
        (f, i) =>
          !lastUploadedFiles[i] ||
          f.name !== lastUploadedFiles[i].name ||
          f.size !== lastUploadedFiles[i].size
      );

    if (filesChanged) {
      setUploadedFileNames([]);
      setLastUploadedFiles([]);
    }

    // Show warning for large files (50MB+)
    const totalSizeMB = getTotalFileSizeMB(next);
    const maxFileMB = Math.max(
      0,
      ...next.map((f) => (f?.size || 0) / (1024 * 1024))
    );
    if (totalSizeMB > 60 || maxFileMB > 60) {
      showToast(
        `Large upload (${Math.round(
          totalSizeMB
        )}MB total) — upload depends on your network speed.`,
        6000
      );
    } else if (totalSizeMB > 50) {
      showToast(
        `Large upload (${Math.round(
          totalSizeMB
        )}MB total) — expect longer processing time.`,
        5000
      );
    }

    // Clear any attention blink once files are added.
    setFileAttention(false);
  };

  // Show toast notification
  const showToast = (message, duration = 4000) => {
    setToast({ message, exiting: false });
    setTimeout(() => {
      setToast((t) => (t ? { ...t, exiting: true } : null));
      setTimeout(() => setToast(null), 300);
    }, duration);
  };

  // Stop/Cancel the current process
  const stopProcess = async () => {
    // Abort any ongoing XHR upload
    if (abortControllerRef.current?.xhr) {
      abortControllerRef.current.xhr.abort();
      abortControllerRef.current.xhr = null;
    }

    // Cancel the polling abort controller
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // Try to cancel the job on the server
    if (currentJobIdRef.current) {
      try {
        await fetch(`/job/${currentJobIdRef.current}/cancel`, {
          method: "POST",
        });
      } catch (e) {
        // Ignore cancel errors
      }
      currentJobIdRef.current = null;
    }
    clearPendingJob(); // Clear localStorage when stopped

    setLoading(false);
    setUploadProgress(0);
    setIsUploading(false);
    setProcessingMessage("");
    // RAM stats will be refreshed by periodic fetch
    showToast("⏹️ Process stopped by user.", 3000);
    setMessages((prev) => [
      ...prev.filter((m, idx) => {
        if (idx !== prev.length - 1) return true;
        return !(m.role === "agent" && m.tone === "status");
      }),
      {
        id: makeId(),
        role: "agent",
        tone: "neutral",
        text: "Process cancelled. Ready for your next request.",
      },
    ]);
  };

  const submit = async (overrideText) => {
    if (!files.length) {
      setError("Please upload at least one file.");
      showToast("Please add a file first.", 3500);
      setFileAttention(true);
      setTimeout(() => setFileAttention(false), 1200);
      return;
    }
    const rawInput = normalizeWhitespace(overrideText ?? prompt);
    if (!rawInput.trim()) {
      setError("Please enter an instruction.");
      return;
    }

    const totalSizeMB = getTotalFileSizeMB(files);

    // Calculate estimated processing time (shown after upload completes)
    const estTime = estimateWaitTime(totalSizeMB, rawInput);

    setLoading(true);
    setError("");
    setResult(null);
    setClarification("");
    setDownloadBlink(false);
    setUploadProgress(0);
    setIsUploading(true);
    setProcessingMessage("");
    // Keep existing RAM stats - will be updated by job status polling

    const rawUserText = rawInput;
    setLastSubmittedPrompt(rawUserText);

    // If user clicked a clarification option, treat it as the final instruction.
    const lastMsg = messages[messages.length - 1];
    const clickedKnownOption =
      pendingClarification &&
      lastMsg?.role === "agent" &&
      isNonEmptyArray(lastMsg?.options) &&
      lastMsg.options.includes(rawUserText);

    const inputSource = clickedKnownOption ? "button" : "text";

    // If we're in a clarification flow, transform the reply into a complete instruction.
    const composed = clickedKnownOption
      ? rawUserText
      : pendingClarification
      ? buildClarifiedPrompt({
          baseInstruction: pendingClarification.baseInstruction,
          question: pendingClarification.question,
          userReply: rawUserText,
        })
      : applyHumanDefaults(rawUserText);

    // Auto-apply 25% compression target for plain "compress" commands
    let finalComposed = composed;
    if (
      !clickedKnownOption &&
      isPlainCompress(composed) &&
      !hasSpecificCompressionTarget(composed)
    ) {
      const fileSizeMB = getTotalFileSizeMB(files);
      const targetMB = Math.max(1, Math.round(fileSizeMB * 0.25));
      finalComposed = `compress to ${targetMB}mb`;
    }

    const userText = normalizePromptForSend(finalComposed);

    // Chat-style: clear input immediately after send
    setPrompt("");

    // Simple status message
    // Determine status message based on whether we can reuse files
    const filesCanBeReused = canReuseFiles();
    const getStatusMessage = () => {
      if (filesCanBeReused) {
        return "Starting processing...";
      }
      return isMobileDevice()
        ? "Uploading files... (Keep app open)"
        : "Uploading files...";
    };

    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: "user",
        tone: "neutral",
        text: pendingClarification ? rawUserText : userText,
      },
      { id: makeId(), role: "agent", tone: "status", text: getStatusMessage() },
    ]);

    try {
      // Create abort controller for polling
      abortControllerRef.current = new AbortController();

      // Request Wake Lock to prevent device sleep
      try {
        wakeLockRef.current = await requestWakeLock();
      } catch (e) {
        // Wake lock not critical
      }

      const updateRamFromStatus = (statusData) => {
        try {
          if (statusData?.ram) {
            console.log("[RAM DEBUG resumePending] RAM data:", statusData.ram);
            setRamStats(statusData.ram);
          } else {
            console.warn(
              "[RAM DEBUG resumePending] No ram field in statusData"
            );
            // Don't clear ramStats - periodic fetch will update it
          }
        } catch {
          // ignore
        }
      };

      let jobId;
      let resultFileNames = [];

      // Check if we can reuse already-uploaded files
      if (filesCanBeReused && uploadedFileNames.length > 0) {
        console.log("[Submit] Reusing uploaded files:", uploadedFileNames);
        setIsUploading(false);

        const formData = new FormData();
        formData.append("file_names", uploadedFileNames.join(","));
        formData.append("prompt", userText);
        if (pendingClarification?.question) {
          formData.append("context_question", pendingClarification.question);
        }
        formData.append("session_id", sessionIdRef.current);
        if (inputSource) formData.append("input_source", inputSource);

        const response = await fetch("/submit-reuse", {
          method: "POST",
          body: formData,
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          // If files not found, fall back to normal upload
          if (response.status === 404) {
            console.log("[Submit] Files expired, re-uploading...");
            setUploadedFileNames([]);
            setLastUploadedFiles([]);
          } else {
            throw new Error(
              errorData.detail || `Server error (${response.status})`
            );
          }
        } else {
          const result = await response.json();
          jobId = result.job_id;
          resultFileNames = result.uploaded_files || uploadedFileNames;
        }
      }

      // If no jobId yet, do normal upload
      if (!jobId) {
        console.log("[Submit] Uploading files...");
        setIsUploading(true);

        const formData = new FormData();
        files.forEach((file) => formData.append("files", file));
        formData.append("prompt", userText);
        if (pendingClarification?.question) {
          formData.append("context_question", pendingClarification.question);
        }
        formData.append("session_id", sessionIdRef.current);
        if (inputSource) formData.append("input_source", inputSource);

        // Upload with progress tracking
        const uploadResult = await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.timeout = 600000;

          xhr.upload.addEventListener("progress", (e) => {
            if (e.lengthComputable) {
              const percent = Math.round((e.loaded / e.total) * 100);
              setUploadProgress(percent);
              setMessages((prev) => {
                const trimmed = prev.filter((m, idx) => {
                  if (idx !== prev.length - 1) return true;
                  return !(m.role === "agent" && m.tone === "status");
                });
                return [
                  ...trimmed,
                  {
                    id: makeId(),
                    role: "agent",
                    tone: "status",
                    text: `Uploading... ${percent}%`,
                  },
                ];
              });
            }
          });

          xhr.addEventListener("load", () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              try {
                resolve(JSON.parse(xhr.responseText));
              } catch (e) {
                reject(new Error("Invalid server response"));
              }
            } else if (xhr.status === 0) {
              reject(new Error("Connection lost"));
            } else {
              reject(new Error(`Server error (${xhr.status})`));
            }
          });

          xhr.addEventListener("error", () =>
            reject(new Error("Connection failed"))
          );
          xhr.addEventListener("timeout", () =>
            reject(new Error("Upload timed out"))
          );
          xhr.addEventListener("abort", () =>
            reject(new DOMException("Cancelled", "AbortError"))
          );

          xhr.open("POST", "/submit");
          xhr.send(formData);
          abortControllerRef.current.xhr = xhr;
        });

        jobId = uploadResult.job_id;
        resultFileNames = uploadResult.uploaded_files || [];
        setIsUploading(false);
        setUploadProgress(100);
      }

      // Store uploaded file names for reuse
      if (resultFileNames.length > 0) {
        setUploadedFileNames(resultFileNames);
        setLastUploadedFiles([...files]);
      }

      currentJobIdRef.current = jobId;

      // Save job to localStorage for recovery
      savePendingJob(jobId, userText, files[0]?.name || "file", estTime);

      // Release wake lock
      await releaseWakeLock(wakeLockRef.current);
      wakeLockRef.current = null;
      setProcessingMessage("Processing...");

      // Update status message for processing
      setMessages((prev) => {
        const trimmed = prev.filter((m, idx) => {
          if (idx !== prev.length - 1) return true;
          return !(m.role === "agent" && m.tone === "status");
        });
        return [
          ...trimmed,
          {
            id: makeId(),
            role: "agent",
            tone: "status",
            text: `Processing...`,
          },
        ];
      });

      // Step 2: Poll for status until done
      let completed = false;
      let pollCount = 0;
      const maxPolls = 600; // 10 minutes at 1 second intervals

      while (!completed && pollCount < maxPolls) {
        // Check if cancelled
        if (abortControllerRef.current?.signal.aborted) {
          throw new DOMException("Cancelled", "AbortError");
        }

        await new Promise((resolve) => setTimeout(resolve, 1000)); // Poll every 1 second
        pollCount++;

        const statusRes = await fetch(`/job/${jobId}/status`, {
          signal: abortControllerRef.current?.signal,
        });

        if (!statusRes.ok) {
          throw new Error(`Status check failed: ${statusRes.status}`);
        }

        const statusData = await statusRes.json();
        const msg = statusData.message || "Processing...";

        const statusText = buildProcessingText(
          msg,
          statusData.estimated_remaining,
          statusData.status
        );

        // Update processing message
        setProcessingMessage(statusText);

        // Update the status bubble - simple progress display
        setMessages((prev) => {
          const trimmed = prev.filter((m, idx) => {
            if (idx !== prev.length - 1) return true;
            return !(m.role === "agent" && m.tone === "status");
          });
          return [
            ...trimmed,
            {
              id: makeId(),
              role: "agent",
              tone: "status",
              text: statusText,
            },
          ];
        });

        if (
          statusData.status === "completed" ||
          statusData.status === "failed"
        ) {
          completed = true;
          currentJobIdRef.current = null;
          clearPendingJob(); // Clear localStorage on completion
          // RAM stats will be refreshed by periodic fetch

          // Remove the status bubble
          setMessages((prev) => {
            const trimmed = prev.filter((m, idx) => {
              if (idx !== prev.length - 1) return true;
              return !(m.role === "agent" && m.tone === "status");
            });
            return trimmed;
          });

          const resultData = statusData.result;

          if (resultData?.status === "success") {
            setResult({
              status: "success",
              output_file: resultData.output_file,
              message: resultData.message,
              operation: resultData.operation,
            });
            setPendingClarification(null);
            setClarification("");
            setProcessingMessage("Complete!");
            // Trigger download button blink
            setDownloadBlink(true);
            setTimeout(() => setDownloadBlink(false), 1600);
            setMessages((prev) => [
              ...prev,
              {
                id: makeId(),
                role: "agent",
                tone: "success",
                text: resultData.message || "Done!",
              },
            ]);
          } else {
            // Handle error or clarification
            const msg = resultData?.message || "Unknown error";
            const hasOptions = isNonEmptyArray(resultData?.options);

            if (hasOptions || looksLikeClarification(msg)) {
              setClarification(msg);
              setPendingClarification({
                question: msg,
                baseInstruction: userText,
              });
              setPrompt("");
              setMessages((prev) => [
                ...prev,
                {
                  id: makeId(),
                  role: "agent",
                  tone: "clarify",
                  text: msg,
                  options: resultData?.options,
                },
              ]);
              setTimeout(() => promptRef.current?.focus(), 0);
            } else {
              setError(msg);
              setPendingClarification(null);
              setMessages((prev) => [
                ...prev,
                { id: makeId(), role: "agent", tone: "error", text: msg },
              ]);
            }
          }
        } else if (statusData.status === "cancelled") {
          completed = true;
          currentJobIdRef.current = null;
          clearPendingJob(); // Clear localStorage on cancel
          // RAM stats will be refreshed by periodic fetch
        }
      }

      if (!completed) {
        throw new Error(
          "Processing timed out. Please try again with a smaller file."
        );
      }
    } catch (err) {
      currentJobIdRef.current = null;
      setUploadProgress(0);
      setIsUploading(false);
      setProcessingMessage("");

      const msg =
        err?.name === "AbortError"
          ? "Request cancelled."
          : `Failed: ${err?.message || err}`;

      if (err?.name !== "AbortError") {
        setError(msg);
        setMessages((prev) => {
          const trimmed = prev.filter((m, idx) => {
            if (idx !== prev.length - 1) return true;
            return !(m.role === "agent" && m.tone === "status");
          });
          return [
            ...trimmed,
            { id: makeId(), role: "agent", tone: "error", text: msg },
          ];
        });
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;

      // Release wake lock if still held (error case)
      await releaseWakeLock(wakeLockRef.current);
      wakeLockRef.current = null;
    }
  };

  const handleOptionClick = async (opt) => {
    if (loading) return;
    // Submit immediately with the option text (do not concatenate with prior prompt).
    await submit(opt);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setError("");
    setResult(null);
    await submit();
  };

  const downloadLabel = inferDownloadLabel(result);
  const hasMultiple = files.length > 1;
  const fileBadge = files.length
    ? `${files.length} file${files.length === 1 ? "" : "s"}`
    : "No files";

  const ramIndicator = useMemo(() => {
    const level = (ramStats?.level || "").toLowerCase();
    if (level === "high") return { label: "High", className: "text-rose-400" };
    if (level === "medium")
      return { label: "Medium", className: "text-amber-300" };
    if (level === "low") return { label: "Low", className: "text-green-400" };
    return { label: "—", className: "text-slate-500" };
  }, [ramStats]);

  const ramPillText = useMemo(() => {
    if (!ramStats) return "Loading...";
    const mb = ramStats.rss_mb || ramStats.peak_rss_mb || null;
    if (mb == null) return "—";
    console.log("[RAM] Pill showing:", mb);
    return `RAM ${mb}MB`;
  }, [ramStats]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-slate-100">
      <div className="cursor-glow" aria-hidden="true" />

      {/* Toast notification for large files - centered on all devices */}
      {toast && (
        <div
          className={cn(
            "fixed top-4 inset-x-4 md:inset-x-auto md:left-1/2 md:-translate-x-1/2 z-50 px-4 py-3 rounded-xl border shadow-lg bg-slate-900/95 max-w-sm mx-auto md:mx-0",
            "border-amber-400/40 text-amber-100",
            toast.exiting ? "toast-exit" : "toast-enter"
          )}
        >
          <div className="flex items-center gap-3 justify-center text-center">
            <span className="text-amber-300 shrink-0">{Icons.clock}</span>
            <span className="text-sm font-medium">{toast.message}</span>
          </div>
        </div>
      )}

      <div className="pointer-events-none fixed inset-0 opacity-70">
        <div className="absolute -top-24 left-1/2 h-64 w-[42rem] -translate-x-1/2 rounded-full bg-cyan-500/10 blur-3xl" />
        <div className="absolute bottom-[-6rem] right-[-6rem] h-72 w-72 rounded-full bg-teal-500/10 blur-3xl" />
      </div>

      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-5 px-4 py-7">
        <header className="flex flex-col gap-2">
          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight text-white flex items-center gap-3">
              <span className="text-cyan-400/90">{Icons.pdf}</span>
              <span className="relative">
                <span className="absolute -inset-2 -z-10 rounded-2xl bg-cyan-400/10 blur-xl" />
                <span className="bg-gradient-to-r from-cyan-200 via-cyan-100 to-teal-200 bg-clip-text text-transparent drop-shadow-[0_0_16px_rgba(34,211,238,0.35)]">
                  OrderMyPDF
                </span>
              </span>
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-slate-300">
              <span className="text-amber-400/80 mr-1 inline-block">
                {Icons.bolt}
              </span>
              Merge, split, compress, OCR, convert (PDF ↔ DOCX/JPG/PNG), remove
              blank/duplicate pages, enhance scans, and flatten PDFs — just
              upload and describe.
            </p>
          </div>
        </header>

        <main className="grid gap-6 md:grid-cols-[1fr_18rem] items-start">
          {/* Mobile Session (compact, above console) */}
          <div className="md:hidden w-full">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-200 flex items-center gap-2">
                    <span className="text-cyan-400/80">{Icons.clipboard}</span>
                    Session
                  </div>
                  <div className="mt-1 text-[11px] text-slate-400 truncate">
                    {files.length
                      ? lastFileName || files[0]?.name
                      : "No files selected"}
                  </div>
                </div>
                <div className="shrink-0 flex items-center gap-2">
                  <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] text-slate-300">
                    {fileBadge}
                  </span>
                  <span
                    className={cn(
                      "rounded-full border px-3 py-1 text-[11px] flex items-center gap-1.5",
                      loading
                        ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-200"
                        : "border-white/10 bg-black/20 text-slate-300"
                    )}
                  >
                    {loading ? (
                      <>
                        <span className="text-cyan-300">{Icons.spinner}</span>
                        {isUploading ? "Uploading" : "Processing"}
                      </>
                    ) : (
                      <>
                        <span className="text-green-400">{Icons.circle}</span>
                        Ready
                      </>
                    )}
                  </span>
                </div>
              </div>

              {/* Live RAM indicator (mobile) - always visible */}
              <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-300">
                <span className={cn(ramIndicator.className)}>
                  {Icons.circle}
                </span>
                <span className="text-slate-200">RAM</span>
                <span className="text-slate-400">
                  {ramStats
                    ? `${ramStats.rss_mb || ramStats.peak_rss_mb || "—"}MB`
                    : "Loading..."}
                </span>
              </div>
            </div>
          </div>

          <section className="rounded-3xl border border-white/10 bg-white/5 shadow-[0_8px_40px_rgba(0,0,0,0.35)] w-full max-w-[95vw] md:max-w-none">
            <div className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-5">
              <div className="space-y-1">
                <div className="text-sm font-medium text-white flex items-center gap-2">
                  <span className="text-cyan-400">{Icons.robot}</span>
                  Agent Console
                </div>
                <div className="text-xs text-slate-400 flex items-center gap-1">
                  <span className="text-slate-500">{Icons.shield}</span>
                  Files processed securely, never stored.
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] text-slate-300 flex items-center gap-1.5">
                  <span className="text-slate-400">{Icons.copy}</span>
                  {fileBadge}
                </span>

                {/* RAM pill - always visible */}
                <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] text-slate-300 flex items-center gap-1.5">
                  <span className={cn(ramIndicator.className)}>
                    {Icons.circle}
                  </span>
                  <span className="text-slate-200">{ramPillText}</span>
                </span>

                <span
                  className={cn(
                    "rounded-full border px-3 py-1 text-[11px] flex items-center gap-1.5",
                    loading
                      ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-200"
                      : "border-white/10 bg-black/20 text-slate-300"
                  )}
                >
                  {loading ? (
                    <>
                      <span className="text-cyan-300">{Icons.spinner}</span>
                      Working…
                    </>
                  ) : (
                    <>
                      <span className="text-green-400">{Icons.circle}</span>
                      Ready
                    </>
                  )}
                </span>
              </div>
            </div>

            <div className="h-[22rem] overflow-auto px-6 py-5 md:h-[26rem]">
              <div className="space-y-4">
                {messages.map((m) => (
                  <div
                    key={m.id}
                    className={cn(
                      "flex w-full animate-fade-slide",
                      m.role === "user" ? "justify-end" : "justify-start"
                    )}
                  >
                    <div
                      className={cn(
                        "max-w-[92%] rounded-2xl border px-4 py-3 text-sm leading-relaxed shadow-sm",
                        m.role === "user"
                          ? "border-cyan-400/20 bg-cyan-400/10 text-slate-50 shadow-[0_0_0_1px_rgba(34,211,238,0.05)]"
                          : "border-white/10 bg-white/5 text-slate-100",
                        m.tone === "success" &&
                          "border-teal-400/25 bg-teal-400/10",
                        m.tone === "error" &&
                          "border-rose-400/25 bg-rose-400/10",
                        m.tone === "clarify" &&
                          "border-amber-300/25 bg-amber-300/10",
                        m.tone === "status" && "border-cyan-400/15 bg-white/5"
                      )}
                    >
                      <div className="flex flex-col gap-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="whitespace-pre-wrap">{m.text}</div>
                          {m.role === "agent" && m.tone === "status" ? (
                            <div className="mt-0.5 inline-flex items-center gap-1.5 text-cyan-300">
                              {Icons.spinner}
                            </div>
                          ) : null}
                        </div>

                        {m.options && m.options.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-2">
                            {m.options.map((opt) => (
                              <button
                                key={opt}
                                type="button"
                                onClick={() => handleOptionClick(opt)}
                                className={cn(
                                  "rounded-lg border px-3 py-1.5 text-xs font-medium transition",
                                  "border-amber-300/30 bg-amber-300/10 text-amber-100 hover:bg-amber-300/20",
                                  "active:scale-95 flex items-center gap-1.5"
                                )}
                              >
                                <span className="text-amber-300/80">
                                  {Icons.arrow}
                                </span>
                                {opt}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}

                {loading ? (
                  <div className="flex w-full justify-start animate-fade-slide">
                    <div className="max-w-[92%] rounded-2xl border border-cyan-400/15 bg-white/5 px-4 py-3 text-sm text-slate-200">
                      <div className="flex flex-col gap-2">
                        <div className="flex items-center gap-3">
                          <span className="text-cyan-400">{Icons.cog}</span>
                          <div className="flex flex-col gap-1">
                            <span className="font-medium">
                              {isUploading
                                ? `Uploading... ${uploadProgress}%`
                                : processingMessage ||
                                  "Processing your request..."}
                            </span>
                          </div>
                        </div>
                        {/* Progress bar only during upload */}
                        {isUploading && (
                          <>
                            <div className="w-full bg-slate-700/50 rounded-full h-2 overflow-hidden">
                              <div
                                className="h-full bg-gradient-to-r from-cyan-500 to-teal-400 rounded-full transition-all duration-300 ease-out"
                                style={{ width: `${uploadProgress}%` }}
                              />
                            </div>
                            <div className="text-xs text-slate-400">
                              Upload speed depends on your network connection
                            </div>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                ) : null}
                <div ref={chatEndRef} />
              </div>
            </div>

            <div className="border-t border-white/10 px-6 py-5">
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="grid gap-3 md:grid-cols-[1fr_auto] md:items-start">
                  <div className="flex items-center gap-3">
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="application/pdf,image/png,image/jpeg,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      multiple
                      onChange={handleFileChange}
                      className="hidden"
                    />
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className={cn(
                        "group inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-sm font-medium transition",
                        "border-white/10 bg-white/5 hover:bg-white/10",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60",
                        fileAttention &&
                          "ring-2 ring-amber-300/60 animate-pulse"
                      )}
                    >
                      <span className="text-cyan-300/90">{Icons.folder}</span>
                      <span className="text-cyan-300/90">Choose files</span>
                      {files.length ? (
                        <span className="ml-1 inline-flex items-center justify-center rounded-full border border-cyan-400/20 bg-cyan-400/10 px-2 py-0.5 text-[11px] text-cyan-100">
                          +
                        </span>
                      ) : null}
                    </button>

                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] text-slate-300">
                          <span className="text-slate-400">{Icons.file}</span>
                          {hasMultiple ? "Multiple files" : "File"}
                        </span>
                        {files.length ? (
                          <span className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[11px] text-cyan-100 animate-chip-in">
                            <span className="text-cyan-300">
                              {Icons.checkCircle}
                            </span>
                            <span className="truncate max-w-[14rem]">
                              {lastFileName || files[0]?.name}
                            </span>
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">
                            No file selected
                          </span>
                        )}
                      </div>
                      {files.length ? (
                        <div className="mt-1 text-[11px] text-slate-400">
                          {hasMultiple
                            ? "Processing all files."
                            : "Ready to process."}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="hidden md:flex flex-col items-stretch gap-2 md:items-end">
                    {/* Desktop Run/Stop buttons */}
                    <div className="flex gap-2">
                      {loading ? (
                        <button
                          type="button"
                          onClick={stopProcess}
                          className={cn(
                            "relative inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition",
                            "border border-rose-400/30 bg-rose-500/20 text-rose-100",
                            "hover:bg-rose-500/30",
                            "focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/60"
                          )}
                        >
                          {Icons.stop}
                          Stop
                        </button>
                      ) : (
                        <button
                          type="submit"
                          className={cn(
                            "relative inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition",
                            "border border-cyan-400/20 bg-cyan-400/10 text-cyan-50",
                            "hover:bg-cyan-400/15",
                            "focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60"
                          )}
                        >
                          {Icons.play}
                          Run
                        </button>
                      )}
                    </div>

                    <div className="w-full md:w-[16rem]">
                      <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
                        <div className="mb-2 flex items-center justify-between">
                          <div className="text-[11px] font-medium text-slate-200 flex items-center gap-1">
                            <span className="text-amber-300/80">
                              {Icons.lightbulb}
                            </span>
                            Ideas
                          </div>
                          <div className="text-[10px] text-slate-400">
                            tap to use
                          </div>
                        </div>

                        <div className="relative h-28 overflow-hidden rounded-xl border border-white/10 bg-black/10">
                          <ul className="suggestion-loop">
                            {promptSuggestions
                              .concat(promptSuggestions)
                              .map((s, idx) => (
                                <li
                                  key={`${s}_${idx}`}
                                  className="suggestion-item"
                                >
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setPrompt(s);
                                      setTimeout(
                                        () => promptRef.current?.focus(),
                                        0
                                      );
                                    }}
                                    className="w-full rounded-lg px-3 py-1.5 text-left text-sm text-slate-200/90 transition hover:bg-white/5 hover:text-white focus:outline-none"
                                  >
                                    {s}
                                  </button>
                                </li>
                              ))}
                          </ul>
                          <div className="pointer-events-none absolute inset-x-0 top-0 h-8 bg-gradient-to-b from-slate-950/90 to-transparent" />
                          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-slate-950/90 to-transparent" />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="relative">
                  <div
                    className={cn(
                      "rounded-2xl border bg-black/20 backdrop-blur-xl",
                      clarification
                        ? "border-amber-300/30 shadow-[0_0_0_1px_rgba(251,191,36,0.12)]"
                        : "border-white/10 shadow-[0_0_0_1px_rgba(34,211,238,0.06)]"
                    )}
                  >
                    <div className="flex items-start gap-3 p-3">
                      <div className="mt-1 h-8 w-8 shrink-0 rounded-xl border border-white/10 bg-white/5 flex items-center justify-center text-cyan-300/80">
                        {Icons.wand}
                      </div>
                      <div className="flex-1">
                        <textarea
                          ref={promptRef}
                          value={prompt}
                          onChange={(e) => setPrompt(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              if (!loading) {
                                handleSubmit({ preventDefault: () => {} });
                              }
                            }
                          }}
                          placeholder={
                            clarification
                              ? "Reply with details so I can continue…"
                              : "e.g. ‘split first page and then compress very tiny’"
                          }
                          rows={2}
                          className={cn(
                            "w-full resize-none bg-transparent text-sm text-slate-100 placeholder:text-slate-400",
                            "focus:outline-none"
                          )}
                        />
                        <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
                          <span>
                            {clarification
                              ? "Clarification needed — keep it conversational."
                              : "Tip: use ‘then’ to chain multiple operations."}
                          </span>
                          <span className="text-slate-500">
                            Enter to send • Shift+Enter newline
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="pointer-events-none absolute -inset-px rounded-2xl opacity-60 blur-sm" />
                </div>

                {/* Mobile buttons row - Run/Stop and Download side by side */}
                <div className="flex md:hidden gap-3">
                  {loading ? (
                    <button
                      type="button"
                      onClick={stopProcess}
                      className={cn(
                        "flex-1 relative inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition",
                        "border border-rose-400/30 bg-rose-500/20 text-rose-100",
                        "hover:bg-rose-500/30",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/60"
                      )}
                    >
                      {Icons.stop}
                      Stop
                    </button>
                  ) : (
                    <button
                      type="submit"
                      className={cn(
                        "flex-1 relative inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition",
                        "border border-cyan-400/20 bg-cyan-400/10 text-cyan-50",
                        "hover:bg-cyan-400/15",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60"
                      )}
                    >
                      {Icons.play}
                      Run
                    </button>
                  )}

                  <a
                    href={
                      result?.output_file
                        ? `/download/${result.output_file}`
                        : "#"
                    }
                    download
                    className={cn(
                      "flex-1 relative inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition",
                      "border",
                      !result?.output_file
                        ? "pointer-events-none border-white/10 bg-white/5 text-slate-400"
                        : "border-teal-400/25 bg-teal-400/10 text-teal-50 hover:bg-teal-400/15",
                      downloadBlink &&
                        result?.output_file &&
                        "animate-download-blink"
                    )}
                  >
                    {Icons.download}
                    {result?.output_file
                      ? "Download"
                      : loading
                      ? "Preparing"
                      : "Download"}
                  </a>
                </div>

                {/* Desktop status + download row */}
                <div className="hidden md:flex flex-row gap-3 items-center justify-between">
                  <div className="text-xs text-slate-400">
                    {error ? (
                      <span className="text-rose-200 flex items-center gap-1">
                        {Icons.error}
                        {error}
                      </span>
                    ) : clarification ? (
                      <span className="text-amber-200 flex items-center gap-1">
                        {Icons.question}
                        Agent needs one more detail.
                      </span>
                    ) : result ? (
                      <span className="text-teal-200 flex items-center gap-1">
                        {Icons.checkCircle}
                        Output ready for download.
                      </span>
                    ) : (
                      <span className="flex items-center gap-1">
                        <span className="text-slate-500">{Icons.upload}</span>
                        Upload files, then describe what you need.
                      </span>
                    )}
                  </div>

                  <a
                    href={
                      result?.output_file
                        ? `/download/${result.output_file}`
                        : "#"
                    }
                    download
                    className={cn(
                      "relative inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold transition",
                      "border",
                      !result?.output_file
                        ? "pointer-events-none border-white/10 bg-white/5 text-slate-400"
                        : "border-teal-400/25 bg-teal-400/10 text-teal-50 hover:bg-teal-400/15",
                      downloadBlink &&
                        result?.output_file &&
                        "animate-download-blink"
                    )}
                  >
                    {Icons.download}
                    {result?.output_file
                      ? downloadLabel
                      : loading
                      ? "Preparing"
                      : "Download"}
                    {loading ? (
                      <span
                        className="absolute inset-0 rounded-xl shimmer"
                        aria-hidden="true"
                      />
                    ) : null}
                  </a>
                </div>
              </form>
            </div>
          </section>

          <aside className="hidden md:block">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="mb-2 text-xs font-medium text-slate-200 flex items-center gap-2">
                <span className="text-cyan-400/80">{Icons.clipboard}</span>
                Session
              </div>
              <div className="space-y-2 text-xs text-slate-300">
                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <div className="text-[11px] text-slate-400 flex items-center gap-1">
                    <span className="text-slate-500">{Icons.file}</span>
                    Selected
                  </div>
                  <div className="truncate">
                    {files.length ? lastFileName || files[0]?.name : "—"}
                  </div>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <div className="text-[11px] text-slate-400 flex items-center gap-1">
                    <span className="text-slate-500">{Icons.signal}</span>
                    Status
                  </div>
                  <div className="flex items-center gap-1.5">
                    {loading ? (
                      <>
                        <span className="text-cyan-400">{Icons.spinner}</span>
                        {isUploading ? "Uploading" : "Processing"}
                      </>
                    ) : result ? (
                      <>
                        <span className="text-teal-400">{Icons.check}</span>
                        Ready
                      </>
                    ) : (
                      <>
                        <span className="text-slate-500">{Icons.minus}</span>
                        Idle
                      </>
                    )}
                  </div>
                </div>

                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <div className="text-[11px] text-slate-400 flex items-center gap-1">
                    <span className="text-slate-500">{Icons.bolt}</span>
                    RAM usage
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={cn(ramIndicator.className)}>
                      {Icons.circle}
                    </span>
                    <span className="text-slate-200">{ramIndicator.label}</span>
                    <span className="text-slate-500">•</span>
                    <span className="text-slate-400">
                      {ramStats
                        ? `${ramStats.rss_mb || ramStats.peak_rss_mb || "—"}MB`
                        : "Loading..."}
                    </span>
                  </div>
                </div>
                {loading && (
                  <div className="rounded-xl border border-cyan-400/20 bg-cyan-400/10 px-3 py-2">
                    {isUploading ? (
                      <>
                        <div className="text-[11px] text-cyan-300 flex items-center gap-1 mb-1">
                          {Icons.upload}
                          Uploading
                        </div>
                        <div className="text-cyan-100 font-medium text-sm mb-1">
                          {uploadProgress}%
                        </div>
                        <div className="w-full bg-slate-700/50 rounded-full h-1.5 overflow-hidden">
                          <div
                            className="h-full bg-cyan-400 rounded-full transition-all duration-300"
                            style={{ width: `${uploadProgress}%` }}
                          />
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="text-[11px] text-cyan-300 flex items-center gap-1 mb-1">
                          {Icons.clock}
                          Processing
                        </div>
                        <div className="text-cyan-100 font-medium text-sm">
                          {processingMessage || "Working..."}
                        </div>
                      </>
                    )}
                  </div>
                )}
                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <div className="text-[11px] text-slate-400 flex items-center gap-1">
                    <span className="text-slate-500">{Icons.export}</span>
                    Output
                  </div>
                  <div className="truncate">{result?.output_file || "—"}</div>
                </div>
              </div>
            </div>
          </aside>
        </main>

        <footer className="pt-2 text-xs text-slate-500">
          © {new Date().getFullYear()} OrderMyPDF — AI-powered PDF operations.
        </footer>
      </div>
    </div>
  );
}
