import React, { useEffect, useMemo, useRef, useState } from "react";

function cn(...parts) {
  return parts.filter(Boolean).join(" ");
}

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
      text: "Tell me what you want to do with your PDFs — I’ll handle the rest.",
    },
  ]);

  const sessionIdRef = useRef(getOrCreateSessionId());

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
      "Try: convert to DOCX",
      "Try: compress to 2MB",
      "Try: rotate page 1 by 90°",
      "Try: add watermark CONFIDENTIAL",
      "Try: add page numbers",
      "Try: extract text",
      "Try: export pages as PNG",
      "Try: OCR this scan",
    ],
    []
  );

  const [statusIndex, setStatusIndex] = useState(0);

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

  const handleFileChange = (e) => {
    const selected = Array.from(e.target.files || []);
    setFiles(selected);
    setLastFileName(selected.length ? selected[selected.length - 1].name : "");
  };

  const submit = async (overrideText) => {
    if (!files.length) {
      setError("Please upload at least one file.");
      return;
    }
    const rawInput = normalizeWhitespace(overrideText ?? prompt);
    if (!rawInput.trim()) {
      setError("Please enter an instruction.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);
    setClarification("");

    const rawUserText = rawInput;

    // If user clicked a clarification option, treat it as the final instruction.
    const lastMsg = messages[messages.length - 1];
    const clickedKnownOption =
      pendingClarification &&
      lastMsg?.role === "agent" &&
      isNonEmptyArray(lastMsg?.options) &&
      lastMsg.options.includes(rawUserText);

    // If we're in a clarification flow, transform the reply into a complete instruction.
    const composed = clickedKnownOption
      ? applyHumanDefaults(rawUserText)
      : pendingClarification
      ? buildClarifiedPrompt({
          baseInstruction: pendingClarification.baseInstruction,
          question: pendingClarification.question,
          userReply: rawUserText,
        })
      : applyHumanDefaults(rawUserText);

    const userText = normalizePromptForSend(composed);

    // Chat-style: clear input immediately after send
    setPrompt("");

    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        role: "user",
        tone: "neutral",
        // Show what user typed, but actually send the clarified prompt.
        text: pendingClarification ? rawUserText : userText,
      },
      { id: makeId(), role: "agent", tone: "status", text: statusPhrases[0] },
    ]);

    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    formData.append("prompt", userText);
    if (pendingClarification?.question) {
      formData.append("context_question", pendingClarification.question);
    }
    formData.append("session_id", sessionIdRef.current);

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000);

      const res = await fetch("/process", {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!res.ok) {
        throw new Error(`HTTP error! status: ${res.status}`);
      }

      const data = await res.json();

      // Remove the last status bubble and replace it with the final response
      setMessages((prev) => {
        const trimmed = prev.filter((m, idx) => {
          // keep everything except the last agent status bubble we appended
          if (idx !== prev.length - 1) return true;
          return !(m.role === "agent" && m.tone === "status");
        });
        return trimmed;
      });

      if (data.status === "success") {
        setResult(data);
        setPendingClarification(null);
        setClarification("");
        setMessages((prev) => [
          ...prev,
          {
            id: makeId(),
            role: "agent",
            tone: "success",
            text: data.message || "Done.",
          },
        ]);
      } else {
        const msg = data.message || "Unknown error";
        const hasOptions = isNonEmptyArray(data.options);
        if (hasOptions || looksLikeClarification(msg)) {
          setClarification(msg);
          setPendingClarification({ question: msg, baseInstruction: userText });
          // When agent asks, clear the input so user can type the answer.
          setPrompt("");
          setMessages((prev) => [
            ...prev,
            {
              id: makeId(),
              role: "agent",
              tone: "clarify",
              text: msg,
              options: data.options,
            },
          ]);
          // Keep focus in the input so it feels like a chat
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
    } catch (err) {
      const msg =
        err?.name === "AbortError"
          ? "Request timed out. Please try again."
          : `Failed to connect to backend: ${err?.message || err}`;
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
    } finally {
      setLoading(false);
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

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 text-slate-100">
      <div className="cursor-glow" aria-hidden="true" />
      <div className="pointer-events-none fixed inset-0 opacity-70">
        <div className="absolute -top-24 left-1/2 h-64 w-[42rem] -translate-x-1/2 rounded-full bg-cyan-500/10 blur-3xl" />
        <div className="absolute bottom-[-6rem] right-[-6rem] h-72 w-72 rounded-full bg-teal-500/10 blur-3xl" />
      </div>

      <div className="relative mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-5 px-4 py-7">
        <header className="flex flex-col gap-2">
          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight text-white">
              <span className="relative">
                <span className="absolute -inset-2 -z-10 rounded-2xl bg-cyan-400/10 blur-xl" />
                <span className="bg-gradient-to-r from-cyan-200 via-cyan-100 to-teal-200 bg-clip-text text-transparent drop-shadow-[0_0_16px_rgba(34,211,238,0.35)]">
                  OrderMyPDF
                </span>
              </span>
            </h1>
            <p className="max-w-2xl text-sm leading-relaxed text-slate-300">
              Upload PDFs, describe what you want — merge, split, delete pages,
              compress, or convert to DOCX.
            </p>
          </div>
        </header>

        <main className="grid gap-6 md:grid-cols-[1fr_18rem]">
          <section className="rounded-3xl border border-white/10 bg-white/5 backdrop-blur-xl shadow-[0_14px_80px_rgba(0,0,0,0.45)] transition-shadow duration-300 hover:shadow-[0_18px_100px_rgba(0,0,0,0.55)]">
            <div className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-5">
              <div className="space-y-1">
                <div className="text-sm font-medium text-white">
                  Agent Console
                </div>
                <div className="text-xs text-slate-400">
                  Your files never leave this session except for processing.
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] text-slate-300">
                  {fileBadge}
                </span>
                <span
                  className={cn(
                    "rounded-full border px-3 py-1 text-[11px]",
                    loading
                      ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-200"
                      : "border-white/10 bg-black/20 text-slate-300"
                  )}
                >
                  {loading ? "Working…" : "Ready"}
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
                            <div className="mt-1 inline-flex items-center gap-1 text-slate-300">
                              <span className="h-1.5 w-1.5 rounded-full bg-cyan-300/80" />
                              <span className="typing-dots" aria-hidden="true">
                                <span>.</span>
                                <span>.</span>
                                <span>.</span>
                              </span>
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
                                  "active:scale-95"
                                )}
                              >
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
                    <div className="max-w-[92%] rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
                      <div className="flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full bg-cyan-400" />
                        <span>{statusPhrases[statusIndex]}</span>
                        <span className="typing-dots" aria-hidden="true">
                          <span>.</span>
                          <span>.</span>
                          <span>.</span>
                        </span>
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
                      accept="application/pdf,image/png,image/jpeg"
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
                        "shadow-[0_8px_30px_rgba(0,0,0,0.35)]"
                      )}
                    >
                      <span className="text-cyan-300/90">Choose files</span>
                      <span className="text-slate-400 group-hover:text-slate-300">
                        +
                      </span>
                    </button>

                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/20 px-3 py-1 text-[11px] text-slate-300">
                          {hasMultiple ? "Multiple files" : "File"}
                        </span>
                        {files.length ? (
                          <span className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[11px] text-cyan-100 animate-chip-in">
                            <span className="h-1.5 w-1.5 rounded-full bg-cyan-300" />
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
                            ? "We’ll process all selected PDFs."
                            : "Ready to process."}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="flex flex-col items-stretch gap-2 md:items-end">
                    <button
                      type="submit"
                      disabled={loading}
                      className={cn(
                        "relative inline-flex items-center justify-center rounded-xl px-5 py-2.5 text-sm font-semibold transition",
                        "border border-cyan-400/20 bg-cyan-400/10 text-cyan-50",
                        "hover:bg-cyan-400/15",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60",
                        loading && "cursor-not-allowed opacity-80"
                      )}
                    >
                      {loading ? (
                        <span className="inline-flex items-center gap-2">
                          <span className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-200/70 border-t-transparent" />
                          Processing
                        </span>
                      ) : (
                        "Run"
                      )}
                      {loading ? (
                        <span
                          className="absolute inset-0 rounded-xl shimmer"
                          aria-hidden="true"
                        />
                      ) : null}
                    </button>

                    <div className="w-full md:w-[16rem]">
                      <div className="rounded-2xl border border-white/10 bg-white/5 p-3 backdrop-blur-xl shadow-[0_12px_60px_rgba(0,0,0,0.30)]">
                        <div className="mb-2 flex items-center justify-between">
                          <div className="text-[11px] font-medium text-slate-200">
                            Prompt ideas
                          </div>
                          <div className="text-[10px] text-slate-400">tap</div>
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
                                      setPrompt(s.replace(/^Try:\s*/i, ""));
                                      setTimeout(
                                        () => promptRef.current?.focus(),
                                        0
                                      );
                                    }}
                                    className="w-full rounded-lg px-3 py-2 text-left text-sm text-slate-200/90 transition hover:bg-white/5 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60"
                                  >
                                    <span className="text-cyan-300/80">
                                      Try:
                                    </span>{" "}
                                    {s.replace(/^Try:\s*/i, "")}
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
                      <div className="mt-1 h-8 w-8 shrink-0 rounded-xl border border-white/10 bg-white/5 p-2 text-center text-sm text-slate-200">
                        ✨
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

                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div className="text-xs text-slate-400">
                    {error ? (
                      <span className="text-rose-200">{error}</span>
                    ) : clarification ? (
                      <span className="text-amber-200">
                        Agent needs one more detail.
                      </span>
                    ) : result ? (
                      <span className="text-teal-200">
                        Output ready for download.
                      </span>
                    ) : (
                      <span>Upload PDFs, then send your instruction.</span>
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
                      "relative inline-flex items-center justify-center rounded-xl px-5 py-2.5 text-sm font-semibold transition",
                      "border",
                      !result?.output_file
                        ? "pointer-events-none border-white/10 bg-white/5 text-slate-400"
                        : "border-teal-400/25 bg-teal-400/10 text-teal-50 hover:bg-teal-400/15 shadow-[0_0_0_1px_rgba(45,212,191,0.12)]"
                    )}
                  >
                    {result?.output_file
                      ? downloadLabel
                      : loading
                      ? "Preparing…"
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
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 backdrop-blur-xl shadow-[0_12px_60px_rgba(0,0,0,0.35)]">
              <div className="mb-2 text-xs font-medium text-slate-200">
                Session
              </div>
              <div className="space-y-2 text-xs text-slate-300">
                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <div className="text-[11px] text-slate-400">Selected</div>
                  <div className="truncate">
                    {files.length ? lastFileName || files[0]?.name : "—"}
                  </div>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <div className="text-[11px] text-slate-400">Status</div>
                  <div>
                    {loading ? "Processing" : result ? "Ready" : "Idle"}
                  </div>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
                  <div className="text-[11px] text-slate-400">Output</div>
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
