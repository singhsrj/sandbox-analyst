import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

/**
 * Clerk's request handler (keeps the Clerk session in sync; it protects nothing by itself: the
 * API checks every token, see api/app/auth.py), plus one redirect: links shared before the
 * landing page existed (`/?t=…`, `/?replay=…`) still open the conversation or recorded run.
 */
export default clerkMiddleware((_auth, request) => {
  const { pathname, searchParams, search } = request.nextUrl;
  if (pathname === "/" && (searchParams.has("t") || searchParams.has("replay"))) {
    return NextResponse.redirect(new URL(`/app${search}`, request.url));
  }
});

export const config = {
  matcher: [
    // Skip Next.js internals and static files, unless found in search params (Clerk's default).
    "/((?!_next|[^?]*\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
