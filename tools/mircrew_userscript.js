// ==UserScript==
// @name         MirCrew Release Crawler
// @namespace    mmc.mircrew
// @version      4.1.0
// @description  Crawl liste + dettagli release (grazie/magnet/size) con salvataggio in IndexedDB.
// @match        *://mircrew-releases.org/releases/*
// @match        *://www.mircrew-releases.org/releases/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==

(function () {
  "use strict";

  const DB_NAME = "mircrew_scraper";
  const DB_VERSION = 1;
  const STORE_RELEASES = "releases";
  const STORE_SETTINGS = "settings";
  const STORE_RUNS = "runs";

  const KEY_SELECTED_CATS = "selected_categories";
  const KEY_FORCE_RECHECK = "force_recheck";
  const KEY_CATEGORY_PROGRESS_PREFIX = "category_progress";
  const KEY_RUNTIME_CONFIG = "runtime_config";
  const KEY_RUN_PHASES = "run_phases";
  const KEY_PANEL_LAYOUT = "panel_layout";
  const BASE_LIST_PATH = "/releases/";

  const DEFAULT_RUNTIME_CONFIG = {
    list_min_delay_ms: 1500,
    list_max_delay_ms: 3500,
    detail_min_delay_ms: 2000,
    detail_max_delay_ms: 5000,
    list_pause_every_links: 25,
    list_pause_seconds: 15,
    detail_pause_every_links: 20,
    detail_pause_seconds: 20,
    list_stop_after_no_new_pages: 2,
    list_backfill_pages_per_run: 30,
    list_seek_max_steps: 120,
    max_consecutive_http_errors: 5,
    head_known_streak_stop: 10,// set to 0 to disable stop based on known streak in head
    head_start_page: 1,
    open_random_release_on_pause: false,
  };

  const DEFAULT_RUN_PHASES = {
    phase1: true,
    phase2: true,
  };

  let running = false;
  let stopRequested = false;
  let categoriesCache = [];
  let runtimeConfig = { ...DEFAULT_RUNTIME_CONFIG };
  let recentReleaseUrls = [];
  const SCRIPT_VERSION = (typeof GM_info !== "undefined" && GM_info && GM_info.script && GM_info.script.version)
    ? String(GM_info.script.version)
    : "unknown";

  function nowIso() {
    return new Date().toISOString();
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function randomDelay(minMs, maxMs) {
    return Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;
  }


  function numInRange(value, fallback, min, max) {
    const n = Number(value);
    if (!Number.isFinite(n)) return fallback;
    return Math.min(max, Math.max(min, Math.round(n)));
  }

  function normalizeRuntimeConfig(raw) {
    const src = raw || {};
    const cfg = {
      list_min_delay_ms: numInRange(src.list_min_delay_ms, DEFAULT_RUNTIME_CONFIG.list_min_delay_ms, 0, 120000),
      list_max_delay_ms: numInRange(src.list_max_delay_ms, DEFAULT_RUNTIME_CONFIG.list_max_delay_ms, 0, 120000),
      detail_min_delay_ms: numInRange(src.detail_min_delay_ms, DEFAULT_RUNTIME_CONFIG.detail_min_delay_ms, 0, 120000),
      detail_max_delay_ms: numInRange(src.detail_max_delay_ms, DEFAULT_RUNTIME_CONFIG.detail_max_delay_ms, 0, 120000),
      list_pause_every_links: numInRange(src.list_pause_every_links, DEFAULT_RUNTIME_CONFIG.list_pause_every_links, 0, 5000),
      list_pause_seconds: numInRange(src.list_pause_seconds, DEFAULT_RUNTIME_CONFIG.list_pause_seconds, 0, 3600),
      detail_pause_every_links: numInRange(src.detail_pause_every_links, DEFAULT_RUNTIME_CONFIG.detail_pause_every_links, 0, 5000),
      detail_pause_seconds: numInRange(src.detail_pause_seconds, DEFAULT_RUNTIME_CONFIG.detail_pause_seconds, 0, 3600),
      list_stop_after_no_new_pages: numInRange(src.list_stop_after_no_new_pages, DEFAULT_RUNTIME_CONFIG.list_stop_after_no_new_pages, 1, 100),
      list_backfill_pages_per_run: numInRange(src.list_backfill_pages_per_run, DEFAULT_RUNTIME_CONFIG.list_backfill_pages_per_run, 1, 5000),
      list_seek_max_steps: numInRange(src.list_seek_max_steps, DEFAULT_RUNTIME_CONFIG.list_seek_max_steps, 1, 5000),
      max_consecutive_http_errors: numInRange(src.max_consecutive_http_errors, DEFAULT_RUNTIME_CONFIG.max_consecutive_http_errors, 1, 200),
      head_known_streak_stop: numInRange(src.head_known_streak_stop, DEFAULT_RUNTIME_CONFIG.head_known_streak_stop, 0, 1000),
      head_start_page: numInRange(src.head_start_page, DEFAULT_RUNTIME_CONFIG.head_start_page, 1, 100000),
      open_random_release_on_pause: src.open_random_release_on_pause === true,
    };

    if (cfg.list_min_delay_ms > cfg.list_max_delay_ms) {
      const t = cfg.list_min_delay_ms;
      cfg.list_min_delay_ms = cfg.list_max_delay_ms;
      cfg.list_max_delay_ms = t;
    }
    if (cfg.detail_min_delay_ms > cfg.detail_max_delay_ms) {
      const t = cfg.detail_min_delay_ms;
      cfg.detail_min_delay_ms = cfg.detail_max_delay_ms;
      cfg.detail_max_delay_ms = t;
    }
    return cfg;
  }

  function normalizeRunPhases(raw) {
    const src = raw || {};
    return {
      phase1: src.phase1 !== false,
      phase2: src.phase2 !== false,
    };
  }

  async function maybeLongPause(everyN, seconds, doneCount, label) {
    if (!everyN || everyN <= 0 || !seconds || seconds <= 0) return;
    if (doneCount > 0 && doneCount % everyN === 0) {
      uiLog(`${label}: pausa di ${seconds}s dopo ${doneCount} richieste.`);
      await sendKeepAlivePing(label);
      if (runtimeConfig.open_random_release_on_pause) {
        maybeOpenRandomReleaseTab(label);
      }
      await sleep(seconds * 1000);
    }
  }

  async function sendKeepAlivePing(label) {
    try {
      await fetch(`${location.origin}${BASE_LIST_PATH}`, {
        credentials: "include",
        cache: "no-store",
      });
      uiLog(`${label}: keep-alive ping ok.`);
    } catch (err) {
      uiLog(`${label}: keep-alive ping fallito (${err}).`);
    }
  }

  function rememberReleaseUrlCandidate(url) {
    const u = normalizeReleaseUrl(String(url || ""));
    if (!u || !/viewtopic\.php\?t=/i.test(u)) return;
    recentReleaseUrls.push(u);
    if (recentReleaseUrls.length > 500) {
      recentReleaseUrls = recentReleaseUrls.slice(recentReleaseUrls.length - 500);
    }
  }

  function pickRandomKnownReleaseUrl() {
    if (recentReleaseUrls.length) {
      const idx = Math.floor(Math.random() * recentReleaseUrls.length);
      return recentReleaseUrls[idx] || null;
    }
    const domUrls = [...document.querySelectorAll('a[href*="viewtopic.php?t="]')]
      .map((a) => absoluteUrl(a.getAttribute("href"), location.href))
      .filter(Boolean);
    if (!domUrls.length) return null;
    const idx = Math.floor(Math.random() * domUrls.length);
    return domUrls[idx] || null;
  }

  function maybeOpenRandomReleaseTab(label) {
    const url = pickRandomKnownReleaseUrl();
    if (!url) {
      uiLog(`${label}: random-open skip (nessuna release disponibile).`);
      return;
    }
    try {
      // Open blank first to retain a window handle that can be closed later.
      const win = window.open("", "_blank");
      if (!win) {
        uiLog(`${label}: random-open bloccato dal browser.`);
        return;
      }
      try {
        win.location.href = url;
      } catch {
        // Fallback for stricter browsers.
        window.open(url, "_blank");
      }
      uiLog(`${label}: random-open ${url}`);
      setTimeout(() => {
        try { win.close(); } catch {}
      }, 15 * 1000); // auto-close after 15s to avoid tab clutter
    } catch (err) {
      uiLog(`${label}: random-open errore (${err}).`);
    }
  }

  function normalizeSpace(s) {
    return (s || "").replace(/\s+/g, " ").trim();
  }

  function absoluteUrl(href, base) {
    try {
      return new URL(href, base).toString();
    } catch {
      return null;
    }
  }

  function extractTopicId(url) {
    try {
      const u = new URL(url);
      return u.searchParams.get("t");
    } catch {
      return null;
    }
  }

  function normalizeReleaseUrl(url) {
    try {
      const u = new URL(url);
      const t = u.searchParams.get("t");
      if (u.pathname.includes("viewtopic.php") && t) {
        return `${u.origin}${u.pathname}?t=${t}`;
      }
      return u.toString();
    } catch {
      return url;
    }
  }

  function buildCategoryUrl(catValue) {
    const u = new URL(window.location.href);
    u.pathname = BASE_LIST_PATH;
    u.searchParams.set("cat", String(catValue));
    u.searchParams.set("sk", "t");
    u.searchParams.set("sd", "d");
    u.searchParams.delete("start");
    u.searchParams.delete("st");
    return u.toString();
  }


  function buildCategoryPageUrl(baseUrl, start) {
    const u = new URL(baseUrl, location.origin);
    const n = Number(start || 0);
    if (Number.isFinite(n) && n > 0) u.searchParams.set("start", String(n));
    else u.searchParams.delete("start");
    return u.toString();
  }

  function parseStartFromUrl(url) {
    try {
      const raw = new URL(url, location.origin).searchParams.get("start");
      const n = Number(raw || 0);
      return Number.isFinite(n) && n >= 0 ? n : 0;
    } catch {
      return 0;
    }
  }

  function detectPageStep(doc, pageUrl) {
    const starts = [0];
    const links = [...doc.querySelectorAll('a[href*="start="]')];
    for (const a of links) {
      const href = a.getAttribute("href");
      if (!href) continue;
      const full = absoluteUrl(href, pageUrl);
      if (!full) continue;
      const n = parseStartFromUrl(full);
      if (n > 0) starts.push(n);
    }

    const uniq = [...new Set(starts)].sort((a, b) => a - b);
    let minDiff = null;
    for (let i = 1; i < uniq.length; i += 1) {
      const d = uniq[i] - uniq[i - 1];
      if (d > 0 && (minDiff == null || d < minDiff)) minDiff = d;
    }
    return minDiff || 25;
  }

  function getCategoryProgressKey(catValue) {
    return `${KEY_CATEGORY_PROGRESS_PREFIX}:${String(catValue || "")}`;
  }


  function calcPageStats(startOffset, pageStep, maxPages) {
    const step = Number(pageStep || 25);
    const maxP = Number(maxPages || 1);
    const current = Math.max(1, Math.floor(Number(startOffset || 0) / step) + 1);
    const clampedCurrent = Math.min(current, maxP);
    const remaining = Math.max(0, maxP - clampedCurrent);
    const percent = maxP > 0 ? Math.min(100, Math.max(0, Math.round((clampedCurrent / maxP) * 100))) : 0;
    return { current: clampedCurrent, total: maxP, remaining, percent };
  }

  function hasUsefulDetailData(row) {
    const hasMagnets = Array.isArray(row.magnet_links) && row.magnet_links.length > 0;
    const hasTorrents = Array.isArray(row.torrent_links) && row.torrent_links.length > 0;
    return hasMagnets || hasTorrents;
  }

  function bumpConsecutiveHttpErrors(runStats, reason) {
    runStats.consecutive_http_errors = (runStats.consecutive_http_errors || 0) + 1;
    uiLog(`${reason}: errori consecutivi=${runStats.consecutive_http_errors}/${runtimeConfig.max_consecutive_http_errors}`);
    if (runStats.consecutive_http_errors >= runtimeConfig.max_consecutive_http_errors) {
      stopRequested = true;
      uiStatus(`Stop automatico: troppi errori consecutivi (${runStats.consecutive_http_errors}).`);
      uiLog("Stop automatico per protezione anti-blocco.");
      return true;
    }
    return false;
  }

  function resetConsecutiveHttpErrors(runStats) {
    runStats.consecutive_http_errors = 0;
  }

  function detectCategorySelect(doc) {
    const preferred = doc.querySelectorAll('select[name*="cat" i], select[id*="cat" i]');
    if (preferred.length) return preferred[0];

    const all = [...doc.querySelectorAll("select")];
    const withOptions = all.filter((sel) => sel.options && sel.options.length > 1);
    if (!withOptions.length) return null;
    withOptions.sort((a, b) => b.options.length - a.options.length);
    return withOptions[0];
  }

  function readCategoriesFromDocument(doc, pageUrl) {
    const sel = detectCategorySelect(doc);
    if (!sel) return [];

    const cats = [];
    for (const opt of [...sel.options]) {
      const value = normalizeSpace(opt.value);
      const label = normalizeSpace(opt.textContent);
      if (!value || !label) continue;
      if (value === "0" || /^tutte?$/i.test(label) || /all/i.test(label)) continue;
      cats.push({ value, label, url: buildCategoryUrl(value), sourcePage: pageUrl });
    }

    const uniq = new Map();
    for (const c of cats) if (!uniq.has(c.value)) uniq.set(c.value, c);
    return [...uniq.values()];
  }

  function parseItalianDateTimeToMs(text) {
    if (!text) return null;
    const m = String(text).match(/(\d{2})\/(\d{2})\/(\d{4})\s*,?\s*(\d{2}):(\d{2})/);
    if (!m) return null;
    const dd = Number(m[1]);
    const mm = Number(m[2]);
    const yyyy = Number(m[3]);
    const hh = Number(m[4]);
    const min = Number(m[5]);
    const d = new Date(yyyy, mm - 1, dd, hh, min, 0, 0);
    const t = d.getTime();
    return Number.isFinite(t) ? t : null;
  }

  function extractReleaseDateInfo(anchor) {
    const candidates = [];
    const row1 = anchor.closest('li.row');
    const row2 = anchor.closest('li');
    const row3 = anchor.closest('tr');
    if (row1) candidates.push(row1);
    if (row2 && row2 !== row1) candidates.push(row2);
    if (row3 && row3 !== row1 && row3 !== row2) candidates.push(row3);
    if (anchor.parentElement) candidates.push(anchor.parentElement);

    for (const node of candidates) {
      const tnode = node.querySelector('time[datetime]');
      if (tnode) {
        const rawDt = normalizeSpace(tnode.getAttribute('datetime') || tnode.textContent || '');
        const parsedDt = Date.parse(rawDt);
        if (Number.isFinite(parsedDt)) return { posted_at_text: rawDt, posted_at_ms: parsedDt };
      }

      const txt = normalizeSpace(node.textContent || '');
      const ms = parseItalianDateTimeToMs(txt);
      if (ms != null) {
        const mm = txt.match(/\d{2}\/\d{2}\/\d{4}\s*,?\s*\d{2}:\d{2}/);
        return { posted_at_text: mm ? normalizeSpace(mm[0]) : null, posted_at_ms: ms };
      }
    }

    return { posted_at_text: null, posted_at_ms: null };
  }

  function extractReleaseLinks(doc, pageUrl) {
    const map = new Map();
    const nodes = [...doc.querySelectorAll('a[href*="viewtopic.php?t="]'), ...doc.querySelectorAll("a.topictitle")];

    for (const a of nodes) {
      const href = a.getAttribute("href");
      if (!href) continue;
      const full = absoluteUrl(href, pageUrl);
      if (!full) continue;
      const normalized = normalizeReleaseUrl(full);
      const topicId = extractTopicId(normalized);
      if (!topicId || map.has(topicId)) continue;

      const dateInfo = extractReleaseDateInfo(a);
      map.set(topicId, {
        release_id: topicId,
        release_url: normalized,
        title_hint: normalizeSpace(a.textContent),
        release_posted_at_text: dateInfo.posted_at_text,
        release_posted_at_ms: dateInfo.posted_at_ms,
      });
    }
    return [...map.values()];
  }

  function findNextPageUrl(doc, pageUrl) {
    const nextRel = doc.querySelector('a[rel="next"]');
    if (nextRel && nextRel.getAttribute("href")) return absoluteUrl(nextRel.getAttribute("href"), pageUrl);
    return null;
  }

  function detectMaxPages(doc) {
    const srOnly = [...doc.querySelectorAll(".pagination .sr-only")]
      .map((x) => normalizeSpace(x.textContent))
      .find((t) => /pagina\s+\d+\s+di\s+\d+/i.test(t));
    if (srOnly) {
      const m = srOnly.match(/pagina\s+\d+\s+di\s+(\d+)/i);
      const n = Number(m && m[1]);
      if (Number.isFinite(n) && n > 0) return n;
    }
    const nums = [...doc.querySelectorAll(".pagination a.button, .pagination li a, .pagination li span")]
      .map((x) => Number((x.textContent || "").trim()))
      .filter((n) => Number.isFinite(n) && n > 0);
    return nums.length ? Math.max(...nums) : null;
  }

  async function fetchDocument(url) {
    const res = await fetch(url, { credentials: "include" });
    const html = await res.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    return { res, html, doc };
  }

  function dedup(arr) {
    return [...new Set((arr || []).filter(Boolean))];
  }

  function extractMagnets(doc, pageUrl) {
    const links = [];
    for (const a of [...doc.querySelectorAll('a[href]')]) {
      const hrefRaw = a.getAttribute("href");
      const href = String(hrefRaw || "").trim();
      if (!href) continue;
      if (!/^magnet:/i.test(href)) continue;
      links.push(absoluteUrl(href, pageUrl) || href);
    }

    // Some releases expose magnet as plain text inside code/pre blocks (no <a href>).
    const codeNodes = [...doc.querySelectorAll("pre code, .codebox code, .codebox, pre")];
    for (const node of codeNodes) {
      const raw = String(node.textContent || "");
      if (!raw) continue;
      const matches = raw.match(/magnet:\?[^\s"'<>]+/gi) || [];
      for (const m of matches) {
        const cleaned = m.replace(/&amp;/gi, "&").trim();
        links.push(cleaned);
      }
    }

    // Fallback scan on full page text for edge templates.
    if (!links.length) {
      const bodyText = String(doc.body ? doc.body.textContent || "" : "");
      const matches = bodyText.match(/magnet:\?[^\s"'<>]+/gi) || [];
      for (const m of matches) {
        const cleaned = m.replace(/&amp;/gi, "&").trim();
        links.push(cleaned);
      }
    }
    return dedup(links);
  }

  function extractTorrentLinks(doc, pageUrl) {
    const links = [];
    for (const a of [...doc.querySelectorAll('a[href]')]) {
      const hrefRaw = a.getAttribute("href");
      const href = String(hrefRaw || "").trim();
      if (!href) continue;
      if (/^magnet:/i.test(href)) continue;
      const full = absoluteUrl(href, pageUrl);
      if (!full) continue;
      try {
        const u = new URL(full);
        const path = (u.pathname || "").toLowerCase();
        const hasTorrentPath = path.endsWith(".torrent");
        const hasTorrentQuery = [...u.searchParams.values()].some((v) => {
          const val = String(v || "").trim().toLowerCase();
          if (!val) return false;
          if (val.endsWith(".torrent")) return true;
          try {
            const nested = new URL(val);
            return (nested.pathname || "").toLowerCase().endsWith(".torrent");
          } catch {
            return false;
          }
        });
        if (!hasTorrentPath && !hasTorrentQuery) continue;
        links.push(u.toString());
      } catch {
        // fallback: ignore malformed URL
      }
    }
    return dedup(links);
  }


  function findThanksUrl(doc, pageUrl) {
    const node =
      doc.querySelector('a[id^="lnk_thanks_post"]') ||
      doc.querySelector('a[href*="thanks="]') ||
      doc.querySelector('a[href*="thank"]');
    if (!node) return null;
    const href = node.getAttribute("href");
    if (!href) return null;
    return absoluteUrl(href, pageUrl);
  }

  function parseMagnetInfo(magnet) {
    if (!magnet) return null;
    try {
      const q = magnet.split("?")[1] || "";
      const p = new URLSearchParams(q);
      const dn = p.get("dn") || "";
      const xl = Number(p.get("xl") || 0);
      return {
        display_name: dn || "",
        size_bytes: Number.isFinite(xl) && xl > 0 ? xl : null,
      };
    } catch {
      return null;
    }
  }

  function parseSizeTextToBytes(sizeText) {
    if (!sizeText) return null;
    const m = sizeText.match(/(\d[\d.,\s]*\d|\d)\s*(TB|GB|MB|KB|B|TIB|GIB|MIB|KIB)\b/i);
    if (!m) return null;
    const rawText = (m[1] || "").trim();
    const unit = (m[2] || "").toUpperCase();

    let raw = null;
    if (unit === "B") {
      // For bytes, separators are usually thousands separators (e.g. 283,750 b).
      const digits = rawText.replace(/[^\d]/g, "");
      raw = Number(digits || 0);
    } else {
      const compact = rawText.replace(/\s+/g, "");
      const hasComma = compact.includes(",");
      const hasDot = compact.includes(".");
      if (hasComma && hasDot) {
        // Use last separator as decimal separator, others as thousands.
        const lastComma = compact.lastIndexOf(",");
        const lastDot = compact.lastIndexOf(".");
        const sepIdx = Math.max(lastComma, lastDot);
        const intPart = compact.slice(0, sepIdx).replace(/[.,]/g, "");
        const decPart = compact.slice(sepIdx + 1).replace(/[.,]/g, "");
        raw = Number(`${intPart}.${decPart}`);
      } else if (hasComma || hasDot) {
        const sep = hasComma ? "," : ".";
        const idx = compact.lastIndexOf(sep);
        const fracLen = compact.length - idx - 1;
        if (fracLen === 3) {
          // Likely thousands separator (e.g. 1,024 MB).
          raw = Number(compact.replace(/[.,]/g, ""));
        } else {
          // Decimal separator.
          raw = Number(compact.replace(",", "."));
        }
      } else {
        raw = Number(compact);
      }
    }

    const factor = {
      B: 1,
      KB: 1024,
      MB: 1024 ** 2,
      GB: 1024 ** 3,
      TB: 1024 ** 4,
      KIB: 1024,
      MIB: 1024 ** 2,
      GIB: 1024 ** 3,
      TIB: 1024 ** 4,
    }[unit];
    if (!factor || !Number.isFinite(raw)) return null;
    return Math.round(raw * factor);
  }

  function extractSize(doc) {
    const text = normalizeSpace(doc.body ? doc.body.textContent : "");
    if (!text) return { size_text_raw: null, size_bytes: null };

    const dimLineMatch = text.match(/(?:dimensione|size)\s*[:\-]?\s*([0-9][0-9.,\s]*\s*(?:TB|GB|MB|KB|B|TIB|GIB|MIB|KIB))/i);
    const candidate = dimLineMatch && dimLineMatch[1] ? normalizeSpace(dimLineMatch[1]) : null;
    if (candidate) {
      const bytes = parseSizeTextToBytes(candidate);
      const plainB = /\bB\b/i.test(candidate) && !/\bKB\b|\bMB\b|\bGB\b|\bTB\b|\bKIB\b|\bMIB\b|\bGIB\b|\bTIB\b/i.test(candidate);
      if (bytes && (!plainB || bytes >= 100000)) return { size_text_raw: candidate, size_bytes: bytes };
    }

    const anySize = text.match(/(\d[\d.,\s]*\s*(?:TB|GB|MB|KB|TIB|GIB|MIB|KIB))/i);
    if (anySize && anySize[1]) {
      const s = normalizeSpace(anySize[1]);
      return { size_text_raw: s, size_bytes: parseSizeTextToBytes(s) };
    }
    return { size_text_raw: null, size_bytes: null };
  }

  function openDb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_RELEASES)) {
          const releases = db.createObjectStore(STORE_RELEASES, { keyPath: "release_id" });
          releases.createIndex("by_category", "category_value", { unique: false });
          releases.createIndex("by_last_seen", "last_seen_at", { unique: false });
        }
        if (!db.objectStoreNames.contains(STORE_SETTINGS)) db.createObjectStore(STORE_SETTINGS, { keyPath: "key" });
        if (!db.objectStoreNames.contains(STORE_RUNS)) db.createObjectStore(STORE_RUNS, { keyPath: "run_id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  function txDone(tx) {
    return new Promise((resolve, reject) => {
      tx.oncomplete = () => resolve(true);
      tx.onabort = () => reject(tx.error || new Error("tx abort"));
      tx.onerror = () => reject(tx.error || new Error("tx error"));
    });
  }

  async function saveSetting(db, key, value) {
    const tx = db.transaction(STORE_SETTINGS, "readwrite");
    tx.objectStore(STORE_SETTINGS).put({ key, value, updated_at: nowIso() });
    await txDone(tx);
  }

  function getSetting(db, key) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_SETTINGS, "readonly");
      const req = tx.objectStore(STORE_SETTINGS).get(key);
      req.onsuccess = () => resolve(req.result ? req.result.value : null);
      req.onerror = () => reject(req.error);
    });
  }

  function getRelease(db, releaseId) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_RELEASES, "readonly");
      const req = tx.objectStore(STORE_RELEASES).get(releaseId);
      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }

  async function upsertRelease(db, item) {
    const existing = await getRelease(db, item.release_id);
    const now = nowIso();
    const merged = existing
      ? {
          ...existing,
          release_url: item.release_url || existing.release_url,
          title_hint: item.title_hint || existing.title_hint,
          category_value: item.category_value || existing.category_value,
          category_label: item.category_label || existing.category_label,
          release_posted_at_text: item.release_posted_at_text || existing.release_posted_at_text || null,
          release_posted_at_ms: Number.isFinite(Number(item.release_posted_at_ms)) ? Number(item.release_posted_at_ms) : (existing.release_posted_at_ms || null),
          last_seen_at: now,
        }
      : {
          release_id: item.release_id,
          release_url: item.release_url,
          title_hint: item.title_hint || "",
          category_value: item.category_value || "",
          category_label: item.category_label || "",
          release_posted_at_text: item.release_posted_at_text || null,
          release_posted_at_ms: Number.isFinite(Number(item.release_posted_at_ms)) ? Number(item.release_posted_at_ms) : null,
          first_seen_at: now,
          last_seen_at: now,
          status: "queued",
          detail_status: "pending",
          detail_updated_at: null,
          detail_error: null,
          detail_error_stage: null,
          thanks_required: false,
          thanks_clicked: false,
          magnet_links: [],
          torrent_links: [],
          size_text_raw: null,
          size_bytes: null,
          magnet_info: null,
        };

    const tx = db.transaction(STORE_RELEASES, "readwrite");
    tx.objectStore(STORE_RELEASES).put(merged);
    await txDone(tx);
    return !existing;
  }

  async function updateReleaseDetails(db, releaseId, patch) {
    const row = await getRelease(db, releaseId);
    if (!row) return false;
    const tx = db.transaction(STORE_RELEASES, "readwrite");
    tx.objectStore(STORE_RELEASES).put({ ...row, ...patch, detail_updated_at: nowIso() });
    await txDone(tx);
    return true;
  }

  function getAllReleases(db) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_RELEASES, "readonly");
      const req = tx.objectStore(STORE_RELEASES).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  async function getDetailQueueByCategories(db, categoryValues, forceRecheck) {
    const selectedSet = new Set((categoryValues || []).map(String));
    const all = await getAllReleases(db);
    const rows = all.filter((r) => selectedSet.has(String(r.category_value || "")));
    const filtered = forceRecheck
      ? rows
      : rows.filter((r) => {
          const status = r.detail_status || "pending";
          if (status === "error" || status === "pending" || status === "running") return true;
          if (status === "ok") return !hasUsefulDetailData(r);
          return true;
        });
    return filtered.sort((a, b) => Number(a.release_id) - Number(b.release_id));
  }


  async function getDetailQueueSummaryByCategories(db, categoryValues, forceRecheck) {
    const selectedSet = new Set((categoryValues || []).map(String));
    const all = await getAllReleases(db);
    const rows = all.filter((r) => selectedSet.has(String(r.category_value || "")));

    const summary = {
      total_selected: rows.length,
      ready_before: 0,
      queued: 0,
      by_reason: {
        force_recheck: 0,
        status_pending: 0,
        status_error: 0,
        status_running: 0,
        status_other: 0,
        ok_but_incomplete: 0,
      },
    };

    const queue = [];
    for (const r of rows) {
      const status = r.detail_status || "pending";
      const useful = hasUsefulDetailData(r);

      if (forceRecheck) {
        queue.push(r);
        summary.by_reason.force_recheck += 1;
        continue;
      }

      if (status === "ok" && useful) {
        summary.ready_before += 1;
        continue;
      }

      queue.push(r);
      if (status === "pending") summary.by_reason.status_pending += 1;
      else if (status === "error") summary.by_reason.status_error += 1;
      else if (status === "running") summary.by_reason.status_running += 1;
      else if (status === "ok" && !useful) summary.by_reason.ok_but_incomplete += 1;
      else summary.by_reason.status_other += 1;
    }

    summary.queued = queue.length;
    queue.sort((a, b) => Number(a.release_id) - Number(b.release_id));
    return { queue, summary };
  }

  async function saveRun(db, runInfo) {
    const tx = db.transaction(STORE_RUNS, "readwrite");
    tx.objectStore(STORE_RUNS).put(runInfo);
    await txDone(tx);
  }

  function getAllRuns(db) {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_RUNS, "readonly");
      const req = tx.objectStore(STORE_RUNS).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  async function getLastRun(db) {
    const runs = await getAllRuns(db);
    if (!runs.length) return null;
    runs.sort((a, b) => (Date.parse(b.ended_at || b.started_at || 0) || 0) - (Date.parse(a.ended_at || a.started_at || 0) || 0));
    return runs[0];
  }

  function downloadText(filename, content, mime) {
    const blob = new Blob([content], { type: mime || "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    URL.revokeObjectURL(a.href);
    a.remove();
  }

  async function createPanel(db) {
    if (document.getElementById("mc-panel")) return;
    const panel = document.createElement("div");
    panel.id = "mc-panel";
    panel.style.cssText = [
      "position:fixed",
      "right:12px",
      "bottom:12px",
      "z-index:999999",
      "width:420px",
      "max-height:90vh",
      "overflow:auto",
      "resize:both",
      "min-width:320px",
      "min-height:260px",
      "background:#111",
      "color:#e8e8e8",
      "padding:10px",
      "border-radius:10px",
      "box-shadow:0 4px 24px rgba(0,0,0,.4)",
      "font:12px/1.4 system-ui, sans-serif",
    ].join(";");
    panel.innerHTML = `
      <div id="mc-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;cursor:move;">
        <div style="font-weight:700;">MirCrew Crawler v${SCRIPT_VERSION}</div>
        <button id="mc-close" style="background:#333;color:#fff;border:0;border-radius:4px;padding:2px 6px;">x</button>
      </div>
      <div id="mc-status" style="background:#1d1d1d;border:1px solid #2b2b2b;border-radius:6px;padding:6px;margin-bottom:8px;">Pronto.</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
        <button id="mc-load-cats">Load Categories</button>
        <button id="mc-start">Start Crawl</button>
        <button id="mc-stop">Stop</button>
        <button id="mc-resume">Resume</button>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
        <button id="mc-select-all">Select All</button>
        <button id="mc-select-none">Select None</button>
        <button id="mc-save-sel">Save Selection</button>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:8px;">
        <label style="display:flex;align-items:center;gap:6px;">
          <input id="mc-run-phase1" type="checkbox" checked>
          <span>Esegui Fase 1</span>
        </label>
        <label style="display:flex;align-items:center;gap:6px;">
          <input id="mc-run-phase2" type="checkbox" checked>
          <span>Esegui Fase 2</span>
        </label>
      </div>
      <label style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
        <input id="mc-force-recheck" type="checkbox">
        <span>Force recheck</span>
      </label>
      <details style="margin-bottom:8px;background:#161616;border:1px solid #2b2b2b;border-radius:6px;padding:6px;">
        <summary style="cursor:pointer;">Config run</summary>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px;">
          <label>List min delay ms <input id="mc-cfg-list-min" type="number" min="0" style="width:100%"></label>
          <label>List max delay ms <input id="mc-cfg-list-max" type="number" min="0" style="width:100%"></label>
          <label>Detail min delay ms <input id="mc-cfg-detail-min" type="number" min="0" style="width:100%"></label>
          <label>Detail max delay ms <input id="mc-cfg-detail-max" type="number" min="0" style="width:100%"></label>
          <label>Pause list every <input id="mc-cfg-list-pause-every" type="number" min="0" style="width:100%"></label>
          <label>Pause list sec <input id="mc-cfg-list-pause-sec" type="number" min="0" style="width:100%"></label>
          <label>Pause detail every <input id="mc-cfg-detail-pause-every" type="number" min="0" style="width:100%"></label>
          <label>Pause detail sec <input id="mc-cfg-detail-pause-sec" type="number" min="0" style="width:100%"></label>
          <label>No-new pages stop <input id="mc-cfg-stop-nonew" type="number" min="1" style="width:100%"></label>
          <label>Backfill pages/run <input id="mc-cfg-backfill" type="number" min="1" style="width:100%"></label>
          <label>Seek max steps <input id="mc-cfg-seek" type="number" min="1" style="width:100%"></label>
          <label>Max http errors <input id="mc-cfg-http-errors" type="number" min="1" style="width:100%"></label>
          <label>Head known streak <input id="mc-cfg-head-known" type="number" min="0" style="width:100%"></label>
          <label>Head start page <input id="mc-cfg-head-start-page" type="number" min="1" style="width:100%"></label>
          <label style="grid-column:1 / span 2;display:flex;align-items:center;gap:6px;"><input id="mc-cfg-open-random-on-pause" type="checkbox"> Open random release on pause</label>
        </div>
        <div style="display:flex;gap:6px;margin-top:6px;">
          <button id="mc-cfg-save">Save Config</button>
          <button id="mc-cfg-reset">Reset Default</button>
        </div>
      </details>
      <div id="mc-cats" style="max-height:180px;overflow:auto;background:#161616;border:1px solid #2b2b2b;border-radius:6px;padding:6px;margin-bottom:8px;"></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
        <button id="mc-stats">Stats</button>
        <button id="mc-export-txt">Export TXT</button>
        <button id="mc-export-json">Export JSON</button>
      </div>
      <textarea id="mc-log" style="width:100%;height:150px;background:#161616;color:#b9e3ff;border:1px solid #2b2b2b;border-radius:6px;"></textarea>
    `;
    document.body.appendChild(panel);
    document.getElementById("mc-close").addEventListener("click", () => panel.remove());

    const defaultLayout = { right: 12, bottom: 12, width: 420, height: null };
    const savedLayout = (db && (await getSetting(db, KEY_PANEL_LAYOUT))) || defaultLayout;
    const layout = {
      right: Number(savedLayout.right),
      bottom: Number(savedLayout.bottom),
      width: Number(savedLayout.width),
      height: Number(savedLayout.height),
    };
    if (Number.isFinite(layout.right)) panel.style.right = `${Math.max(0, layout.right)}px`;
    if (Number.isFinite(layout.bottom)) panel.style.bottom = `${Math.max(0, layout.bottom)}px`;
    if (Number.isFinite(layout.width) && layout.width >= 320) panel.style.width = `${layout.width}px`;
    if (Number.isFinite(layout.height) && layout.height >= 260) panel.style.height = `${layout.height}px`;

    let drag = null;
    const header = document.getElementById("mc-header");
    if (header) {
      header.addEventListener("mousedown", (ev) => {
        if (ev.button !== 0) return;
        drag = {
          startX: ev.clientX,
          startY: ev.clientY,
          startRight: parseInt(panel.style.right || "12", 10) || 12,
          startBottom: parseInt(panel.style.bottom || "12", 10) || 12,
        };
        ev.preventDefault();
      });
    }

    const savePanelLayout = async () => {
      if (!db) return;
      const rect = panel.getBoundingClientRect();
      const right = Math.max(0, Math.round(window.innerWidth - rect.right));
      const bottom = Math.max(0, Math.round(window.innerHeight - rect.bottom));
      const width = Math.round(rect.width);
      const height = Math.round(rect.height);
      await saveSetting(db, KEY_PANEL_LAYOUT, { right, bottom, width, height });
    };

    document.addEventListener("mousemove", (ev) => {
      if (!drag) return;
      const dx = ev.clientX - drag.startX;
      const dy = ev.clientY - drag.startY;
      panel.style.right = `${Math.max(0, drag.startRight - dx)}px`;
      panel.style.bottom = `${Math.max(0, drag.startBottom - dy)}px`;
    });

    document.addEventListener("mouseup", async () => {
      if (!drag) return;
      drag = null;
      await savePanelLayout();
    });

    let resizeTimer = null;
    panel.addEventListener("mouseup", async () => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(async () => {
        await savePanelLayout();
      }, 120);
    });
  }

  function uiStatus(msg) {
    const el = document.getElementById("mc-status");
    if (el) el.textContent = msg;
    console.log("[MirCrew]", msg);
  }

  function uiLog(msg) {
    const el = document.getElementById("mc-log");
    const line = `[${new Date().toLocaleTimeString()}] ${msg}`;
    if (el) {
      el.value += `${line}\n`;
      el.scrollTop = el.scrollHeight;
    }
    console.log("[MirCrew]", msg);
  }

  function formatHumanDateTime(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "-";
    return d.toLocaleString("it-IT", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  }

  function renderCategories(cats, selectedValues) {
    const box = document.getElementById("mc-cats");
    if (!box) return;
    box.innerHTML = "";
    if (!cats.length) {
      box.textContent = "Nessuna categoria trovata nella pagina corrente.";
      return;
    }
    const selectedSet = new Set(selectedValues || []);
    for (const c of cats) {
      const row = document.createElement("label");
      row.style.cssText = "display:flex;align-items:center;gap:6px;padding:2px 0;";
      const checked = selectedSet.has(c.value);
      row.innerHTML = `<input type="checkbox" class="mc-cat-cb" value="${c.value}" ${checked ? "checked" : ""}> <span>${c.label} <small style='color:#888'>(cat=${c.value})</small></span>`;
      box.appendChild(row);
    }
  }

  function selectedCategoryValues() {
    return [...document.querySelectorAll(".mc-cat-cb:checked")].map((x) => x.value);
  }

  function isForceRecheckEnabled() {
    const el = document.getElementById("mc-force-recheck");
    return Boolean(el && el.checked);
  }


  function getRunPhasesFromUi() {
    const p1 = document.getElementById("mc-run-phase1");
    const p2 = document.getElementById("mc-run-phase2");
    return {
      phase1: Boolean(p1 && p1.checked),
      phase2: Boolean(p2 && p2.checked),
    };
  }

  function setRunPhasesUi(phases) {
    const p = normalizeRunPhases(phases);
    const p1 = document.getElementById("mc-run-phase1");
    const p2 = document.getElementById("mc-run-phase2");
    if (p1) p1.checked = p.phase1;
    if (p2) p2.checked = p.phase2;
  }

  function fillRuntimeConfigUi(cfg) {
    const c = normalizeRuntimeConfig(cfg);
    const set = (id, v) => {
      const el = document.getElementById(id);
      if (el) el.value = String(v);
    };
    set("mc-cfg-list-min", c.list_min_delay_ms);
    set("mc-cfg-list-max", c.list_max_delay_ms);
    set("mc-cfg-detail-min", c.detail_min_delay_ms);
    set("mc-cfg-detail-max", c.detail_max_delay_ms);
    set("mc-cfg-list-pause-every", c.list_pause_every_links);
    set("mc-cfg-list-pause-sec", c.list_pause_seconds);
    set("mc-cfg-detail-pause-every", c.detail_pause_every_links);
    set("mc-cfg-detail-pause-sec", c.detail_pause_seconds);
    set("mc-cfg-stop-nonew", c.list_stop_after_no_new_pages);
    set("mc-cfg-backfill", c.list_backfill_pages_per_run);
    set("mc-cfg-seek", c.list_seek_max_steps);
    set("mc-cfg-http-errors", c.max_consecutive_http_errors);
    set("mc-cfg-head-known", c.head_known_streak_stop);
    set("mc-cfg-head-start-page", c.head_start_page);
    const rnd = document.getElementById("mc-cfg-open-random-on-pause");
    if (rnd) rnd.checked = c.open_random_release_on_pause === true;
  }

  function readRuntimeConfigFromUi() {
    const read = (id) => {
      const el = document.getElementById(id);
      return el ? Number(el.value) : null;
    };
    return normalizeRuntimeConfig({
      list_min_delay_ms: read("mc-cfg-list-min"),
      list_max_delay_ms: read("mc-cfg-list-max"),
      detail_min_delay_ms: read("mc-cfg-detail-min"),
      detail_max_delay_ms: read("mc-cfg-detail-max"),
      list_pause_every_links: read("mc-cfg-list-pause-every"),
      list_pause_seconds: read("mc-cfg-list-pause-sec"),
      detail_pause_every_links: read("mc-cfg-detail-pause-every"),
      detail_pause_seconds: read("mc-cfg-detail-pause-sec"),
      list_stop_after_no_new_pages: read("mc-cfg-stop-nonew"),
      list_backfill_pages_per_run: read("mc-cfg-backfill"),
      list_seek_max_steps: read("mc-cfg-seek"),
      max_consecutive_http_errors: read("mc-cfg-http-errors"),
      head_known_streak_stop: read("mc-cfg-head-known"),
      head_start_page: read("mc-cfg-head-start-page"),
      open_random_release_on_pause: Boolean(document.getElementById("mc-cfg-open-random-on-pause")?.checked),
    });
  }

  function filterBySelectedCategories(rows) {
    const selected = new Set(selectedCategoryValues().map(String));
    if (!selected.size) return [];
    return (rows || []).filter((r) => selected.has(String(r.category_value || "")));
  }

  async function loadCategories(db) {
    const cats = readCategoriesFromDocument(document, location.href);
    categoriesCache = cats;
    const saved = (await getSetting(db, KEY_SELECTED_CATS)) || [];
    const savedSet = new Set(saved);
    const initialSelected = cats.filter((c) => savedSet.has(c.value)).map((c) => c.value);
    renderCategories(cats, initialSelected.length ? initialSelected : cats.map((c) => c.value));
    uiStatus(`Categorie trovate: ${cats.length}`);
    uiLog(`Load categories completato (${cats.length}).`);
  }

  async function saveSelection(db) {
    const vals = selectedCategoryValues();
    await saveSetting(db, KEY_SELECTED_CATS, vals);
    uiStatus(`Selezione salvata (${vals.length} categorie).`);
    uiLog(`Saved selected categories: ${vals.join(", ")}`);
  }

  async function crawlCategoryList(db, category, runStats) {
    let pageCount = 0;
    let newCount = 0;
    let noNewPages = 0;

    uiLog(`Fase 1: categoria '${category.label}' start: ${category.url}`);

    let headRes, headDoc;
    try {
      ({ res: headRes, doc: headDoc } = await fetchDocument(category.url));
    } catch (err) {
      uiLog(`Fase 1 error head ${category.label}: ${err}`);
      bumpConsecutiveHttpErrors(runStats, `Fase 1 head ${category.label}`);
      return;
    }

    if (!headRes.ok) {
      uiLog(`Fase 1 stop head ${category.label}: HTTP ${headRes.status}`);
      bumpConsecutiveHttpErrors(runStats, `Fase 1 head ${category.label} http=${headRes.status}`);
      return;
    }

    resetConsecutiveHttpErrors(runStats);

    const pageStep = detectPageStep(headDoc, category.url);
    const maxPages = detectMaxPages(headDoc) || 1;
    const maxStart = Math.max(0, (maxPages - 1) * pageStep);

    const stateKey = getCategoryProgressKey(category.value);
    const state = (await getSetting(db, stateKey)) || {};

    const checkpointMs = Number(state.checkpoint_ms || 0);
    const checkpointTopicId = String(state.checkpoint_topic_id || "");
    let hintStart = Number(state.hint_start || 0);
    if (!Number.isFinite(hintStart)) hintStart = 0;
    hintStart = Math.min(Math.max(0, hintStart), maxStart);

    // Mini-fase HEAD: parte sempre da pagina 1 e si ferma quando trova N release gia note consecutive.
    const headKnownStop = runtimeConfig.head_known_streak_stop;
    const headStartPage = Math.max(1, Number(runtimeConfig.head_start_page || 1));
    const headStartOffset = Math.min(maxStart, Math.max(0, (headStartPage - 1) * pageStep));
    let headKnownStreak = 0;
    let headPageUrl = buildCategoryPageUrl(category.url, headStartOffset);
    let headPages = 0;
    let headNew = 0;
    uiLog(`Fase 1 ${category.label}: mini-fase HEAD da pagina=${headStartPage} (start=${headStartOffset}), stop_soglia=${headKnownStop === 0 ? "OFF" : headKnownStop}.`);

    outerHead:
    while (headPageUrl && !stopRequested) {
      let res, doc;
      try {
        if (headPages === 0 && headStartOffset === 0) {
          res = headRes;
          doc = headDoc;
        } else {
          ({ res, doc } = await fetchDocument(headPageUrl));
        }
      } catch (err) {
        uiLog(`Fase 1 HEAD error ${category.label} p${headPages + 1}: ${err}`);
        bumpConsecutiveHttpErrors(runStats, `Fase 1 HEAD ${category.label} p${headPages + 1}`);
        break;
      }

      if (!res.ok) {
        uiLog(`Fase 1 HEAD stop ${category.label}: HTTP ${res.status}`);
        bumpConsecutiveHttpErrors(runStats, `Fase 1 HEAD ${category.label} http=${res.status}`);
        break;
      }

      resetConsecutiveHttpErrors(runStats);
      headPages += 1;
      pageCount += 1;

      const links = extractReleaseLinks(doc, headPageUrl);
      for (const l of links) rememberReleaseUrlCandidate(l.release_url);
      let addedThisPage = 0;
      let knownThisPage = 0;

      for (const l of links) {
        const created = await upsertRelease(db, { ...l, category_value: category.value, category_label: category.label });
        if (created) {
          addedThisPage += 1;
          headNew += 1;
          newCount += 1;
          runStats.new_links += 1;
          headKnownStreak = 0;
        } else {
          knownThisPage += 1;
          headKnownStreak += 1;
          if (headKnownStop > 0 && headKnownStreak >= headKnownStop) {
            break outerHead;
          }
        }
      }

      runStats.pages_scanned += 1;
      const statsHead = calcPageStats(parseStartFromUrl(headPageUrl), pageStep, maxPages);
      uiStatus(`Fase 1 HEAD ${category.label} pagina~${statsHead.current}/${statsHead.total} (${statsHead.percent}%) | known_streak=${headKnownStreak}/${headKnownStop} | nuovi_cat=${newCount}`);
      uiLog(`Fase 1 HEAD ${category.label} pagina~${statsHead.current}/${statsHead.total}: links=${links.length}, nuovi_pagina=${addedThisPage}, noti_pagina=${knownThisPage}, known_streak=${headKnownStreak}/${headKnownStop}`);

      const nextUrl = findNextPageUrl(doc, headPageUrl);
      if (!nextUrl || nextUrl === headPageUrl) break;
      headPageUrl = nextUrl;

      await maybeLongPause(runtimeConfig.list_pause_every_links, runtimeConfig.list_pause_seconds, headPages, "Fase 1 HEAD");
      await sleep(randomDelay(runtimeConfig.list_min_delay_ms, runtimeConfig.list_max_delay_ms));
    }

    if (headKnownStop > 0 && headKnownStreak >= headKnownStop) {
      uiLog(`Fase 1 ${category.label}: mini-fase HEAD stop su soglia known_streak=${headKnownStreak}/${headKnownStop}.`);
    } else if (headKnownStop === 0) {
      uiLog(`Fase 1 ${category.label}: mini-fase HEAD completata senza soglia (head_known_streak_stop=0).`);
    }
    uiLog(`Fase 1 ${category.label}: mini-fase HEAD completata: pagine=${headPages}, nuovi=${headNew}.`);

    let startOffset = 0;

    if (checkpointMs > 0 || checkpointTopicId) {
      let seekStart = hintStart;
      let seekFound = false;

      for (let i = 0; i < runtimeConfig.list_seek_max_steps && !stopRequested; i += 1) {
        const seekUrl = buildCategoryPageUrl(category.url, seekStart);
        let res, doc;
        try {
          ({ res, doc } = await fetchDocument(seekUrl));
        } catch (err) {
          uiLog(`Fase 1 seek ${category.label} start=${seekStart} err=${err}`);
          bumpConsecutiveHttpErrors(runStats, `Fase 1 seek ${category.label} start=${seekStart}`);
          break;
        }

        if (!res.ok) {
          uiLog(`Fase 1 seek ${category.label} start=${seekStart} HTTP=${res.status}`);
          bumpConsecutiveHttpErrors(runStats, `Fase 1 seek ${category.label} start=${seekStart} http=${res.status}`);
          break;
        }

        resetConsecutiveHttpErrors(runStats);
        pageCount += 1;
        runStats.pages_scanned += 1;

        const links = extractReleaseLinks(doc, seekUrl);
        const statsSeek = calcPageStats(seekStart, pageStep, maxPages);
        uiLog(`Fase 1 seek ${category.label}: pagina~${statsSeek.current}/${statsSeek.total} (${statsSeek.percent}%) restanti~${statsSeek.remaining}, start=${seekStart}`);
        const ids = links.map((x) => String(x.release_id || ""));
        const withDate = links.map((x) => Number(x.release_posted_at_ms || 0)).filter((n) => Number.isFinite(n) && n > 0);

        const hasTopic = checkpointTopicId ? ids.includes(checkpointTopicId) : false;
        const minMs = withDate.length ? Math.min(...withDate) : null;
        const maxMs = withDate.length ? Math.max(...withDate) : null;

        if (hasTopic) {
          seekFound = true;
          break;
        }

        let nextSeekStart = seekStart;
        if (checkpointMs > 0 && minMs != null && maxMs != null) {
          // Default order sd=d: page 1 newer, growing start goes to older.
          if (checkpointMs > maxMs) {
            nextSeekStart = Math.max(0, seekStart - pageStep);
          } else if (checkpointMs < minMs) {
            nextSeekStart = Math.min(maxStart, seekStart + pageStep);
          } else {
            seekFound = true;
            break;
          }
        } else {
          nextSeekStart = Math.min(maxStart, seekStart + pageStep);
        }

        if (nextSeekStart === seekStart) {
          uiLog(`Fase 1 seek ${category.label}: stallo su start=${seekStart}, passo alla scan.`);
          break;
        }

        seekStart = nextSeekStart;
        await maybeLongPause(runtimeConfig.list_pause_every_links, runtimeConfig.list_pause_seconds, i + 1, "Fase 1 seek");
        await sleep(randomDelay(runtimeConfig.list_min_delay_ms, runtimeConfig.list_max_delay_ms));
      }

      startOffset = seekFound ? Math.max(0, seekStart - pageStep) : seekStart;
    }

    let offset = Math.min(Math.max(0, startOffset), maxStart);
    let scannedBackfillPages = 0;
    let newCheckpointMs = checkpointMs;
    let newCheckpointTopicId = checkpointTopicId;

    while (!stopRequested && offset <= maxStart) {
      const pageUrl = buildCategoryPageUrl(category.url, offset);
      let res, doc;
      try {
        ({ res, doc } = await fetchDocument(pageUrl));
      } catch (err) {
        uiLog(`Fase 1 error ${category.label} start=${offset}: ${err}`);
        bumpConsecutiveHttpErrors(runStats, `Fase 1 ${category.label} start=${offset}`);
        break;
      }

      if (!res.ok) {
        uiLog(`Fase 1 stop ${category.label} start=${offset}: HTTP ${res.status}`);
        bumpConsecutiveHttpErrors(runStats, `Fase 1 ${category.label} start=${offset} http=${res.status}`);
        break;
      }

      resetConsecutiveHttpErrors(runStats);
      pageCount += 1;
      scannedBackfillPages += 1;

      const links = extractReleaseLinks(doc, pageUrl);
      for (const l of links) rememberReleaseUrlCandidate(l.release_url);

      let addedThisPage = 0;
      for (const l of links) {
        const created = await upsertRelease(db, { ...l, category_value: category.value, category_label: category.label });
        if (created) {
          addedThisPage += 1;
          newCount += 1;
          runStats.new_links += 1;
        }
      }

      runStats.pages_scanned += 1;
      const statsScan = calcPageStats(offset, pageStep, maxPages);
      uiStatus(`Fase 1 ${category.label} pagina~${statsScan.current}/${statsScan.total} (${statsScan.percent}%) | restanti~${statsScan.remaining} | nuovi_cat=${newCount} | nuovi_run=${runStats.new_links}`);
      uiLog(`Fase 1 ${category.label} pagina~${statsScan.current}/${statsScan.total} (${statsScan.percent}%) start=${offset}: links=${links.length}, nuovi_pagina=${addedThisPage}, nuovi_cat=${newCount}, restanti~${statsScan.remaining}`);

      const dated = links
        .map((x) => ({ id: String(x.release_id || ""), ms: Number(x.release_posted_at_ms || 0) }))
        .filter((x) => Number.isFinite(x.ms) && x.ms > 0)
        .sort((a, b) => a.ms - b.ms || Number(a.id || 0) - Number(b.id || 0));
      if (dated.length) {
        const oldest = dated[0];
        if (newCheckpointMs <= 0 || oldest.ms < newCheckpointMs || (oldest.ms === newCheckpointMs && oldest.id !== newCheckpointTopicId)) {
          newCheckpointMs = oldest.ms;
          newCheckpointTopicId = oldest.id;
        }
      }

      await saveSetting(db, stateKey, {
        checkpoint_ms: newCheckpointMs || null,
        checkpoint_topic_id: newCheckpointTopicId || null,
        hint_start: offset,
        page_step: pageStep,
        updated_at: nowIso(),
      });

      if (links.length > 0 && addedThisPage === 0) {
        noNewPages += 1;
      } else if (addedThisPage > 0) {
        noNewPages = 0;
      }
      if (noNewPages >= runtimeConfig.list_stop_after_no_new_pages) {
        uiLog(`Fase 1 ${category.label}: stop incrementale (pagine consecutive senza nuovi=${noNewPages}).`);
        break;
      }

      if (scannedBackfillPages >= runtimeConfig.list_backfill_pages_per_run) {
        uiLog(`Fase 1 ${category.label}: raggiunto budget pagine run=${runtimeConfig.list_backfill_pages_per_run}, riprendero da start=${offset + pageStep}.`);
        break;
      }

      await maybeLongPause(runtimeConfig.list_pause_every_links, runtimeConfig.list_pause_seconds, scannedBackfillPages, "Fase 1");
      offset += pageStep;
      if (offset > maxStart) break;
      await sleep(randomDelay(runtimeConfig.list_min_delay_ms, runtimeConfig.list_max_delay_ms));
    }

    uiLog(`Fase 1: categoria '${category.label}' completata: pagine=${pageCount}, nuovi=${newCount}`);
  }

  async function crawlReleaseDetail(db, release, runInfo, idx, total, displayIdx, displayTotal) {
    if (stopRequested) return;
    const rid = release.release_id;
    const url = release.release_url;
    rememberReleaseUrlCandidate(url);

    // Reset volatile detail fields on every run, to avoid stale data from previous attempts.
    await updateReleaseDetails(db, rid, {
      detail_status: "running",
      detail_error: null,
      detail_error_stage: null,
      thanks_required: false,
      thanks_clicked: false,
      magnet_links: [],
      torrent_links: [],
      size_text_raw: null,
      size_bytes: null,
      magnet_info: null,
    });

    try {
      uiLog(`Fase 2 ${displayIdx}/${displayTotal} id=${rid}: START (run ${idx}/${total})`);
      let { res, doc } = await fetchDocument(url);
      if (!res.ok) {
        bumpConsecutiveHttpErrors(runInfo, `Fase 2 id=${rid} release_page http=${res.status}`);
        runInfo.details_error += 1;
        await updateReleaseDetails(db, rid, {
          detail_status: "error",
          detail_error: `HTTP ${res.status}`,
          detail_error_stage: "release_page",
        });
        uiLog(`Fase 2 ${displayIdx}/${displayTotal} id=${rid}: ESITO=ERROR stage=release_page http=${res.status} (run ${idx}/${total})`);
        return;
      }
      resetConsecutiveHttpErrors(runInfo);

      let magnets = extractMagnets(doc, url);
      let torrents = extractTorrentLinks(doc, url);
      const thanksUrl = findThanksUrl(doc, url);
      let thanksClicked = false;

      if (!magnets.length && thanksUrl) {
        const thanks = await fetchDocument(thanksUrl);
        if (thanks.res.ok) {
          resetConsecutiveHttpErrors(runInfo);
          doc = thanks.doc;
          magnets = extractMagnets(doc, url);
          torrents = extractTorrentLinks(doc, url);
          thanksClicked = true;
        } else {
          bumpConsecutiveHttpErrors(runInfo, `Fase 2 id=${rid} thanks_page http=${thanks.res.status}`);
          runInfo.details_error += 1;
          await updateReleaseDetails(db, rid, {
            detail_status: "error",
            detail_error: `HTTP ${thanks.res.status}`,
            detail_error_stage: "thanks_page",
            thanks_required: true,
            thanks_clicked: false,
          });
          uiLog(`Fase 2 ${displayIdx}/${displayTotal} id=${rid}: ESITO=ERROR stage=thanks_page http=${thanks.res.status} (run ${idx}/${total})`);
          return;
        }
      }

      const size = extractSize(doc);
      const magInfo = parseMagnetInfo(magnets[0] || null);
      const finalSizeBytes = (magInfo && magInfo.size_bytes) || size.size_bytes || null;
      const hasDownloadLinks = magnets.length > 0 || torrents.length > 0;
      const detailStatus = hasDownloadLinks ? "ok" : "incomplete";
      const detailError = hasDownloadLinks ? null : "NO_DOWNLOAD_LINKS";

      await updateReleaseDetails(db, rid, {
        detail_status: detailStatus,
        detail_error: detailError,
        detail_error_stage: hasDownloadLinks ? null : "no_links",
        thanks_required: Boolean(thanksUrl),
        thanks_clicked: thanksClicked,
        magnet_links: magnets,
        torrent_links: torrents,
        size_text_raw: size.size_text_raw,
        size_bytes: finalSizeBytes,
        magnet_info: magInfo,
      });

      if (hasDownloadLinks) runInfo.details_ok += 1;
      else runInfo.details_error += 1;
      if (thanksUrl) runInfo.details_thanks += 1;
      if (magnets.length) runInfo.details_with_magnet += 1;
      if (finalSizeBytes) runInfo.details_with_size += 1;
      uiStatus(`Fase 2 ${displayIdx}/${displayTotal} | ok=${runInfo.details_ok} err=${runInfo.details_error}`);
      const thanksState = thanksClicked ? "clicked" : (thanksUrl ? "required_not_clicked" : "not_required");
      const sizeSource = (magInfo && magInfo.size_bytes) ? "magnet_xl" : (size.size_bytes ? "page_text" : "none");
      const outcome = hasDownloadLinks ? "OK" : "INCOMPLETE";
      uiLog(`Fase 2 ${displayIdx}/${displayTotal} id=${rid}: ESITO=${outcome} magnet=${magnets.length} torrent=${torrents.length} thanks=${thanksState} size_bytes=${finalSizeBytes || "-"} size_source=${sizeSource} size_raw=${size.size_text_raw || "-"} (run ${idx}/${total})`);
    } catch (err) {
      bumpConsecutiveHttpErrors(runInfo, `Fase 2 id=${rid} exception`);
      runInfo.details_error += 1;
      await updateReleaseDetails(db, rid, {
        detail_status: "error",
        detail_error: String(err || "unknown"),
        detail_error_stage: "exception",
      });
      uiLog(`Fase 2 ${displayIdx}/${displayTotal} id=${rid}: ESITO=ERROR stage=exception err=${err} (run ${idx}/${total})`);
    }
  }

  async function runCrawl(db, categories, resumeRunId, runPhasesInput) {
    if (!categories.length) {
      uiStatus("Nessuna categoria selezionata.");
      return;
    }

    const runPhases = normalizeRunPhases(runPhasesInput || getRunPhasesFromUi());
    if (!runPhases.phase1 && !runPhases.phase2) {
      uiStatus("Seleziona almeno una fase (Fase 1 o Fase 2).");
      uiLog("Run annullata: nessuna fase selezionata.");
      return;
    }

    running = true;
    stopRequested = false;
    const runId = resumeRunId || `run_${Date.now()}`;
    const runInfo = {
      run_id: runId,
      started_at: nowIso(),
      ended_at: null,
      state: "running",
      categories: categories.map((c) => ({ value: c.value, label: c.label })),
      phases: runPhases,
      pages_scanned: 0,
      new_links: 0,
      total_links: 0,
      details_total: 0,
      details_ok: 0,
      details_error: 0,
      details_thanks: 0,
      details_with_magnet: 0,
      details_with_size: 0,
      consecutive_http_errors: 0,
    };
    await saveSetting(db, "current_run", runId);
    await saveRun(db, runInfo);

    uiStatus(`Run avviata (${categories.length} categorie).`);
    uiLog(`Run options: phase1=${runPhases.phase1}, phase2=${runPhases.phase2}`);

    if (runPhases.phase1) {
      uiLog("Start fase 1: crawl liste.");
      for (const c of categories) {
        if (stopRequested) break;
        await crawlCategoryList(db, c, runInfo);
        await saveRun(db, runInfo);
      }
    } else {
      uiLog("Fase 1 disattivata dall'utente.");
    }

    if (!stopRequested && runPhases.phase2) {
      const selectedValues = categories.map((c) => String(c.value));
      const forceRecheck = isForceRecheckEnabled();
      const { queue, summary } = await getDetailQueueSummaryByCategories(db, selectedValues, forceRecheck);
      runInfo.details_total = queue.length;

      uiLog(`Start fase 2: totale_categoria=${summary.total_selected}, gia_ok=${summary.ready_before}, in_coda=${summary.queued}, force_recheck=${forceRecheck}.`);
      if (!forceRecheck) {
        uiLog(`Fase 2 skip summary: pending=${summary.by_reason.status_pending}, error=${summary.by_reason.status_error}, running=${summary.by_reason.status_running}, ok_incompleti=${summary.by_reason.ok_but_incomplete}, other=${summary.by_reason.status_other}, gia_ok_completi=${summary.ready_before}.`);
      } else {
        uiLog(`Fase 2 skip summary: force_recheck attivo, nessuno skip.`);
      }

      for (let i = 0; i < queue.length && !stopRequested; i += 1) {
        const displayIdx = summary.ready_before + i + 1;
        const displayTotal = summary.total_selected;
        await crawlReleaseDetail(db, queue[i], runInfo, i + 1, queue.length, displayIdx, displayTotal);
        await saveRun(db, runInfo);
        await maybeLongPause(runtimeConfig.detail_pause_every_links, runtimeConfig.detail_pause_seconds, i + 1, "Fase 2");
        await sleep(randomDelay(runtimeConfig.detail_min_delay_ms, runtimeConfig.detail_max_delay_ms));
      }
    } else if (!runPhases.phase2) {
      uiLog("Fase 2 disattivata dall'utente.");
    }

    const all = await getAllReleases(db);
    runInfo.total_links = all.length;
    runInfo.ended_at = nowIso();
    runInfo.state = stopRequested ? "stopped" : "completed";
    await saveRun(db, runInfo);
    await saveSetting(db, "current_run", null);
    running = false;

    const msg = stopRequested
      ? `Run interrotta. links=${runInfo.total_links}, nuovi=${runInfo.new_links}, dettagli_ok=${runInfo.details_ok}, dettagli_err=${runInfo.details_error}`
      : `Run completata. links=${runInfo.total_links}, nuovi=${runInfo.new_links}, dettagli_ok=${runInfo.details_ok}, dettagli_err=${runInfo.details_error}`;
    uiStatus(msg);
    uiLog(msg);
  }

  async function resumeCrawl(db) {
    const currentRun = await getSetting(db, "current_run");
    if (!currentRun) {
      uiStatus("Nessuna run in sospeso. Uso Start Crawl.");
      return;
    }
    uiLog(`Resume richiesto (run=${currentRun}), riparto con dedup su topic id.`);
    const selected = selectedCategoryValues();
    const cats = categoriesCache.filter((c) => selected.includes(c.value));
    await runCrawl(db, cats, currentRun, getRunPhasesFromUi());
  }

  async function showStats(db) {
    const all = await getAllReleases(db);
    const byCat = new Map();
    let withDetails = 0;
    for (const r of all) {
      const key = r.category_label || r.category_value || "unknown";
      byCat.set(key, (byCat.get(key) || 0) + 1);
      if (r.detail_status === "ok") withDetails += 1;
    }
    uiLog(`Totale release in DB: ${all.length}`);
    uiLog(`Release con dettagli ok: ${withDetails}`);
    for (const [cat, count] of [...byCat.entries()].sort((a, b) => b[1] - a[1])) {
      uiLog(` - ${cat}: ${count}`);
    }
    uiStatus(`Stats: ${all.length} release.`);
  }

  async function exportTxt(db) {
    const all = await getAllReleases(db);
    const filtered = filterBySelectedCategories(all);
    const lines = filtered.sort((a, b) => Number(a.release_id) - Number(b.release_id)).map((x) => x.release_url);
    downloadText(`mircrew_links_${Date.now()}.txt`, `${lines.join("\n")}\n`, "text/plain;charset=utf-8");
    uiStatus(`Export TXT completato (${lines.length}/${all.length} links, categorie selezionate).`);
  }

  async function exportJson(db) {
    const all = await getAllReleases(db);
    const filtered = filterBySelectedCategories(all);
    downloadText(`mircrew_links_${Date.now()}.json`, JSON.stringify(filtered, null, 2), "application/json;charset=utf-8");
    uiStatus(`Export JSON completato (${filtered.length}/${all.length} records, categorie selezionate).`);
  }

  async function wireUi(db) {
    await createPanel(db);

    const savedForce = await getSetting(db, KEY_FORCE_RECHECK);
    const forceEl = document.getElementById("mc-force-recheck");
    if (forceEl) {
      forceEl.checked = Boolean(savedForce);
      forceEl.addEventListener("change", async () => {
        await saveSetting(db, KEY_FORCE_RECHECK, Boolean(forceEl.checked));
        uiLog(`Force recheck: ${forceEl.checked}`);
      });
    }

    const savedPhases = normalizeRunPhases((await getSetting(db, KEY_RUN_PHASES)) || DEFAULT_RUN_PHASES);
    setRunPhasesUi(savedPhases);
    const phase1El = document.getElementById("mc-run-phase1");
    const phase2El = document.getElementById("mc-run-phase2");
    const savePhases = async () => {
      const p = getRunPhasesFromUi();
      await saveSetting(db, KEY_RUN_PHASES, p);
      uiLog(`Run phases: phase1=${p.phase1}, phase2=${p.phase2}`);
    };
    if (phase1El) phase1El.addEventListener("change", savePhases);
    if (phase2El) phase2El.addEventListener("change", savePhases);

    runtimeConfig = normalizeRuntimeConfig((await getSetting(db, KEY_RUNTIME_CONFIG)) || DEFAULT_RUNTIME_CONFIG);
    fillRuntimeConfigUi(runtimeConfig);

    const cfgSaveBtn = document.getElementById("mc-cfg-save");
    if (cfgSaveBtn) {
      cfgSaveBtn.addEventListener("click", async () => {
        runtimeConfig = readRuntimeConfigFromUi();
        await saveSetting(db, KEY_RUNTIME_CONFIG, runtimeConfig);
        fillRuntimeConfigUi(runtimeConfig);
        uiStatus("Config salvata.");
        uiLog(`Config aggiornata: list_delay=${runtimeConfig.list_min_delay_ms}-${runtimeConfig.list_max_delay_ms}ms, detail_delay=${runtimeConfig.detail_min_delay_ms}-${runtimeConfig.detail_max_delay_ms}ms, seek_max=${runtimeConfig.list_seek_max_steps}, backfill=${runtimeConfig.list_backfill_pages_per_run}`);
      });
    }

    const cfgResetBtn = document.getElementById("mc-cfg-reset");
    if (cfgResetBtn) {
      cfgResetBtn.addEventListener("click", async () => {
        runtimeConfig = { ...DEFAULT_RUNTIME_CONFIG };
        fillRuntimeConfigUi(runtimeConfig);
        await saveSetting(db, KEY_RUNTIME_CONFIG, runtimeConfig);
        uiStatus("Config resettata ai default.");
        uiLog("Config runtime resettata ai valori di default.");
      });
    }

    document.getElementById("mc-load-cats").addEventListener("click", async () => {
      await loadCategories(db);
    });
    document.getElementById("mc-select-all").addEventListener("click", () => {
      document.querySelectorAll(".mc-cat-cb").forEach((cb) => (cb.checked = true));
    });
    document.getElementById("mc-select-none").addEventListener("click", () => {
      document.querySelectorAll(".mc-cat-cb").forEach((cb) => (cb.checked = false));
    });
    document.getElementById("mc-save-sel").addEventListener("click", async () => {
      await saveSelection(db);
    });
    document.getElementById("mc-start").addEventListener("click", async () => {
      if (running) return uiStatus("Crawl già in esecuzione.");
      const selected = selectedCategoryValues();
      const cats = categoriesCache.filter((c) => selected.includes(c.value));
      await runCrawl(db, cats, null, getRunPhasesFromUi());
    });
    document.getElementById("mc-stop").addEventListener("click", () => {
      if (!running) return uiStatus("Nessuna crawl in corso.");
      stopRequested = true;
      uiStatus("Stop richiesto...");
      uiLog("Stop richiesto dall'utente.");
    });
    document.getElementById("mc-resume").addEventListener("click", async () => {
      if (running) return uiStatus("Crawl già in esecuzione.");
      await resumeCrawl(db);
    });
    document.getElementById("mc-stats").addEventListener("click", async () => {
      await showStats(db);
    });
    document.getElementById("mc-export-txt").addEventListener("click", async () => {
      await exportTxt(db);
    });
    document.getElementById("mc-export-json").addEventListener("click", async () => {
      await exportJson(db);
    });

    await loadCategories(db);
  }

  async function init() {
    if (!/mircrew-releases\.org$/i.test(location.hostname)) return;
    try {
      const db = await openDb();
      await wireUi(db);

      const all = await getAllReleases(db);
      const lastRun = await getLastRun(db);
      uiLog(`Init completato. Release in DB: ${all.length}.`);

      const byCat = new Map();
      for (const r of all) {
        const key = r.category_label || r.category_value || "unknown";
        byCat.set(key, (byCat.get(key) || 0) + 1);
      }
      for (const [cat, count] of [...byCat.entries()].sort((a, b) => b[1] - a[1])) {
        uiLog(`Init per categoria -> ${cat}: ${count}`);
      }

      if (lastRun) {
        uiLog(`Ultima run: inizio=${formatHumanDateTime(lastRun.started_at)}, fine=${formatHumanDateTime(lastRun.ended_at)}`);
      } else {
        uiLog("Ultima run: nessuna run salvata.");
      }
    } catch (err) {
      console.error("[MirCrew] init error", err);
      alert(`MirCrew userscript init error: ${err}`);
    }
  }

  init();
})();

