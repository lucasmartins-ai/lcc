// The shipped model files, copied byte for byte from the lcc package at build time.
import type { APIRoute } from "astro";
import { models } from "../../lib/models.ts";
import { lcc, readBytes } from "../../lib/sources.ts";

export const getStaticPaths = () => models.map((m) => ({ params: { file: m.name }, props: { path: m.path } }));

export const GET: APIRoute = ({ props }) =>
  new Response(new Uint8Array(readBytes(lcc, props.path as string)), { headers: { "Content-Type": "application/json" } });
