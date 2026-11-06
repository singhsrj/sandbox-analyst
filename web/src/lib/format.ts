export function formatSeconds(seconds: number): string {
  if (!Number.isFinite(seconds)) return "-";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${Math.round(seconds % 60)} s`;
}

export function formatCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatRelative(iso: string, now = Date.now()): string {
  const diff = Math.max(0, now - new Date(iso).getTime());
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

const ANSI = /\u001b\[[0-9;?]*[ -/]*[@-~]/g;

/** Terminal colour codes in sandbox output are noise in a <pre>; also avoids an ANSI renderer. */
export function stripAnsi(text: string): string {
  return text.replace(ANSI, "");
}

const MARKDOWN_IMAGE = /!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/g;

/**
 * Agents embed charts with sandbox paths ("![chart](/home/user/outputs/x.png)") or bare file
 * names. Those paths only exist inside the sandbox, so the browser would request them from this
 * site and show a broken image (found on the live deployment). Charts are shown in the Files
 * panel, so such references become a short pointer there. Absolute http(s) images are left alone.
 */
export function replaceSandboxImages(markdown: string): string {
  return markdown.replace(MARKDOWN_IMAGE, (whole, alt: string, src: string) => {
    if (/^(https?:|data:)/i.test(src)) return whole;
    const name = src.split("/").filter(Boolean).pop() ?? src;
    const label = alt.trim() || name;
    return `*(${label}: see ${name} in Files)*`;
  });
}
