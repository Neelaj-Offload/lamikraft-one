import { NextResponse, type NextRequest } from "next/server";

/**
 * Passes the requested path to server layouts as `x-lk-path`, so a signed-out deep link
 * returns there after sign-in (`/login?next=`). It does nothing else: authentication is the
 * bootstrap call and every FastAPI endpoint. /api, Next assets and files are excluded, so
 * uploads are never buffered here (frontend_verification §3).
 */
export function proxy(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set("x-lk-path", `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!api/|_next/|licences/|favicon.ico|.*\\.[a-zA-Z0-9]+$).*)"],
};
