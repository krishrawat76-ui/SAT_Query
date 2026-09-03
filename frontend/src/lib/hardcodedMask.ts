"use client";

// Hardcoded stand-in for a real segmentation model. When the query asks to
// highlight the water body, this draws a fixed translucent blob over the
// analyzed image so "highlight the water body" has a visible result on the
// map — a placeholder to prove the masking pipeline works end-to-end, meant
// to be replaced by a real water-segmentation model later.

const WATER_RE = /\bwater\b/i;
const HIGHLIGHT_VERB_RE = /highlight|show|locate|find|mark|outline|point out/i;

export function isWaterHighlightQuery(query: string): boolean {
    return WATER_RE.test(query) && HIGHLIGHT_VERB_RE.test(query);
}

function loadImage(url: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
        const img = new Image();
        if (/^https?:\/\//.test(url)) img.crossOrigin = "anonymous";
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error(`Failed to load image for masking: ${url}`));
        img.src = url;
    });
}

/** The "water body" highlight itself — a fixed translucent blue ellipse. */
function drawWaterEllipse(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    ctx.fillStyle = "rgba(56, 130, 246, 0.55)";
    ctx.strokeStyle = "rgba(96, 165, 250, 0.95)";
    ctx.lineWidth = Math.max(2, width * 0.006);
    ctx.beginPath();
    ctx.ellipse(width * 0.52, height * 0.58, width * 0.26, height * 0.17, 0.3, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
}

function canvasToObjectUrl(canvas: HTMLCanvasElement): Promise<string> {
    return new Promise((resolve, reject) => {
        canvas.toBlob((blob) => {
            if (blob) resolve(URL.createObjectURL(blob));
            else reject(new Error("Failed to encode mask canvas"));
        }, "image/png");
    });
}

/**
 * Draws a fixed translucent blue blob over `sourceUrl` and returns a new
 * object URL — the "water body" highlight. `sourceUrl` can be a backend-
 * served PNG, a browser object URL, or a data URL; any raster we can draw
 * into a canvas.
 */
export async function generateWaterBodyMaskUrl(sourceUrl: string): Promise<string> {
    const img = await loadImage(sourceUrl);
    const width = img.naturalWidth || img.width;
    const height = img.naturalHeight || img.height;

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas 2D context unavailable");

    ctx.drawImage(img, 0, 0, width, height);
    drawWaterEllipse(ctx, width, height);

    return canvasToObjectUrl(canvas);
}

/**
 * Fallback for when no real preview of the uploaded file could be obtained
 * (e.g. a real-world GeoTIFF whose compression codec `geotiff.js` can't
 * decode, such as JPEG2000). Draws the same water-body highlight over a
 * flat neutral background sized to the file's real dimensions, so the
 * hardcoded demo always has something to show once the trigger query
 * matches — not meant to look like real imagery, just to prove the masking
 * UI works end-to-end regardless of the source file's format.
 */
export async function generatePlaceholderMaskUrl(width: number, height: number): Promise<string> {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas 2D context unavailable");

    ctx.fillStyle = "#1e293b"; // slate-800, matches the app's dark theme
    ctx.fillRect(0, 0, width, height);
    drawWaterEllipse(ctx, width, height);

    return canvasToObjectUrl(canvas);
}
