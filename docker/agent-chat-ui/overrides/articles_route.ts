import type { NextRequest } from "next/server";
import { promises as fs } from "node:fs";
import path from "node:path";

export const runtime = "nodejs";

function getContentType(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  switch (ext) {
    case ".md":
      return "text/markdown; charset=utf-8";
    case ".txt":
      return "text/plain; charset=utf-8";
    case ".json":
      return "application/json; charset=utf-8";
    case ".png":
      return "image/png";
    case ".jpg":
    case ".jpeg":
      return "image/jpeg";
    case ".webp":
      return "image/webp";
    case ".gif":
      return "image/gif";
    case ".svg":
      return "image/svg+xml";
    case ".pdf":
      return "application/pdf";
    default:
      return "application/octet-stream";
  }
}

function isPathInsideBaseDir(filePath: string, baseDir: string): boolean {
  const resolvedBase = path.resolve(baseDir);
  const resolvedPath = path.resolve(filePath);
  if (resolvedPath === resolvedBase) return true;
  return resolvedPath.startsWith(resolvedBase + path.sep);
}

export async function GET(req: NextRequest, context: any) {
  const slug = (context?.params?.slug as string[] | undefined) ?? [];
  if (!Array.isArray(slug) || slug.length === 0) {
    return new Response("Not Found", { status: 404 });
  }

  const baseDir = process.env.ARTICLES_FS_BASE_DIR || "/articles";
  const requestedPath = path.join(baseDir, ...slug);

  if (!isPathInsideBaseDir(requestedPath, baseDir)) {
    return new Response("Bad Request", { status: 400 });
  }

  const url = new URL(req.url);
  const download = url.searchParams.get("download") !== "0";

  try {
    const stat = await fs.stat(requestedPath);
    if (!stat.isFile()) {
      return new Response("Not Found", { status: 404 });
    }

    const data = await fs.readFile(requestedPath);
    const contentType = getContentType(requestedPath);
    const filename = path.basename(requestedPath);

    const headers = new Headers();
    headers.set("Content-Type", contentType);
    headers.set("Cache-Control", "no-store");

    if (download && !contentType.startsWith("image/")) {
      headers.set("Content-Disposition", `attachment; filename="${filename}"`);
    } else {
      headers.set("Content-Disposition", `inline; filename="${filename}"`);
    }

    return new Response(data, { status: 200, headers });
  } catch {
    return new Response("Not Found", { status: 404 });
  }
}

