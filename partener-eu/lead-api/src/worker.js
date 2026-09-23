export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const allowed = new Set(["https://partener.eu","https://www.partener.eu"]);
    const corsOrigin = allowed.has(origin) ? origin : "https://partener.eu";
    const headers = {
      "Access-Control-Allow-Origin": corsOrigin,
      "Access-Control-Allow-Methods": "POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Vary": "Origin",
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    };
    if (request.method === "OPTIONS") return new Response(null,{status:204,headers});
    if (request.method !== "POST") return new Response(JSON.stringify({ok:false,error:"METHOD_NOT_ALLOWED"}),{status:405,headers});

    let body;
    try { body = await request.json(); } catch {
      return new Response(JSON.stringify({ok:false,error:"INVALID_JSON"}),{status:400,headers});
    }

    const clean = v => String(v ?? "").trim();
    const company = clean(body.company).slice(0,180);
    const contact_name = clean(body.name).slice(0,160);
    const contact = clean(body.contact).slice(0,220);
    const employees = Number.parseInt(body.employees,10);
    const delivery_format = clean(body.format).slice(0,80);
    const website = clean(body.website).slice(0,220); // honeypot
    if (website) return new Response(JSON.stringify({ok:true}),{status:200,headers});
    if (!company || !contact_name || !contact || !Number.isFinite(employees) || employees < 1 || !delivery_format) {
      return new Response(JSON.stringify({ok:false,error:"VALIDATION_ERROR"}),{status:422,headers});
    }

    const ip = request.headers.get("CF-Connecting-IP") || "";
    const ua = request.headers.get("User-Agent") || "";
    const now = new Date().toISOString();
    const lead_id = crypto.randomUUID();

    await env.DB.prepare(
      `INSERT INTO rpm_leads
      (lead_id, created_at, company, contact_name, contact, employees, delivery_format, source_url, referrer, utm_source, utm_medium, utm_campaign, utm_content, status, notes, ip_hash, user_agent)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', '', ?, ?)`
    ).bind(
      lead_id, now, company, contact_name, contact, employees, delivery_format,
      clean(body.source_url).slice(0,500), clean(body.referrer).slice(0,500),
      clean(body.utm_source).slice(0,120), clean(body.utm_medium).slice(0,120),
      clean(body.utm_campaign).slice(0,180), clean(body.utm_content).slice(0,180),
      await sha256(ip + (env.IP_SALT || "")), ua.slice(0,500)
    ).run();

    return new Response(JSON.stringify({ok:true,lead_id}),{status:201,headers});
  }
};

async function sha256(text){
  const data = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,"0")).join("");
}
