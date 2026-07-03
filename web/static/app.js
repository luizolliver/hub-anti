/* ============================================================
   Observatório Barretos — front (v3)
   Todas as telas consomem a API real (web/app.py → src/consultas
   e src/reports/dossie). Sem dados mock.
   ============================================================ */

/* Bandeiras: metadados de apresentação vêm do backend (web/flags_meta.py). */
const FLAGS = window.FLAGS_META || {};

/* ================= HELPERS ================= */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const fmtBRL = v => (v==null||v==="") ? "—" : Number(v).toLocaleString("pt-BR",{style:"currency",currency:"BRL",maximumFractionDigits:0});
const fmtCNPJ = c => (c||"").replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/,"$1.$2.$3/$4-$5");
const fmtData = d => d ? String(d).slice(0,10).split("-").reverse().join("/") : "—";
const lvlColor = l => l>=7 ? "var(--red)" : l>=4 ? "var(--amber)" : "var(--lime)";
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const esc = s => (s==null?"":String(s)).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function meterHTML(lvl){
  let bars="";
  for(let i=1;i<=9;i++) bars += `<i class="${i<=lvl?"on":""}"></i>`;
  return `<div class="meter" style="--mc:${lvlColor(lvl)}" role="img" aria-label="Nível de atenção ${lvl}">${bars}</div>`;
}
function chipsHTML(flags){
  if(!flags || !flags.length) return `<span class="chip" style="color:var(--txt-3);border-color:var(--line-2)">sem bandeiras</span>`;
  return flags.map(f=>{
    const fl = FLAGS[f];
    if(!fl) return `<span class="chip amber" title="${esc(f)}">${esc(f)}</span>`;
    return `<span class="chip ${fl.tone}" title="${esc(fl.desc)}">${esc(fl.label)}</span>`;
  }).join("");
}
function supCardHTML(s,i){
  return `<article class="supcard" style="animation-delay:${Math.min(i*60,420)}ms">
    <div class="sup-meter"><span class="lvl-num" style="color:${lvlColor(s.lvl)}">${s.lvl}</span>${meterHTML(s.lvl)}</div>
    <div>
      <div class="sup-name">${esc(s.name)}</div>
      <div class="sup-cnpj">${fmtCNPJ(s.cnpj)}</div>
      <div class="sup-flags">${chipsHTML(s.flags)}</div>
      <div class="sup-money"><span>movimentado:</span> ${fmtBRL(s.paid)}</div>
    </div>
    <button class="gobtn" data-profile="${s.cnpj}">Ver perfil →</button>
  </article>`;
}

/* count-up animation com prefixo/sufixo/decimais */
function countUp(el,target,{prefix="",suffix="",dec=0}={}){
  const fmt = v => prefix + v.toLocaleString("pt-BR",{minimumFractionDigits:dec,maximumFractionDigits:dec}) + suffix;
  if(reduced){el.textContent = fmt(target); return;}
  const dur=1100, t0=performance.now();
  (function tick(t){
    const p=Math.min((t-t0)/dur,1), e=1-Math.pow(1-p,3), v=target*e;
    el.textContent = fmt(v);
    if(p<1) requestAnimationFrame(tick);
  })(t0);
}

/* skeleton simulation on nav switch */
function withSkeleton(container,build,delay=550){
  container.innerHTML = `<div class="skeleton">`+`<div class="sk sk-block"></div>`.repeat(3)+`</div>`;
  setTimeout(build, reduced ? 0 : delay);
}
async function getJSON(url){
  const r = await fetch(url);
  if(!r.ok) throw new Error("HTTP "+r.status);
  return r.json();
}

/* ================= INÍCIO: números + topo ================= */
async function renderStats(){
  const g=$("#statsGrid");
  try{
    const {stats} = await getJSON("/api/metricas");
    g.innerHTML = stats.map(s=>`
      <div class="stat ${s.alert?"alert":""}">
        <div class="stat-label">${esc(s.label)}</div>
        <div class="stat-val"
             data-target="${s.val}" data-prefix="${s.prefix||""}"
             data-suffix="${s.suffix||""}" data-dec="${s.dec||0}">0</div>
        <div class="stat-src">fonte · ${esc(s.src)}</div>
      </div>`).join("");
    const io=new IntersectionObserver(es=>es.forEach(e=>{
      if(e.isIntersecting){
        const el=e.target;
        countUp(el,+el.dataset.target,{prefix:el.dataset.prefix,suffix:el.dataset.suffix,dec:+el.dataset.dec});
        io.unobserve(el);
      }
    }),{threshold:.4});
    g.querySelectorAll(".stat-val").forEach(el=>io.observe(el));
  }catch(err){
    g.innerHTML = `<div class="noresult">Não foi possível carregar os números (${err.message}).</div>`;
  }
}
async function renderHomeTop(){
  const box=$("#homeTop");
  try{
    const data = await getJSON("/api/ranking?minimo=1&limite=3");
    box.innerHTML = data.suppliers.map(supCardHTML).join("")
      || `<div class="noresult">Sem fornecedores no ranking.</div>`;
  }catch(err){
    box.innerHTML = `<div class="noresult">Não foi possível carregar o topo (${err.message}).</div>`;
  }
}

/* ================= RANKING (dados reais) ================= */
function rankingParams(){
  const min = +$("#lvlRange").value;
  const qt  = +$('.seg [aria-pressed="true"]').dataset.qt;
  const p = new URLSearchParams({minimo:String(min), limite:String(qt)});
  const mod = $("#fltModalidade")?.value;
  const org = $("#fltOrgao")?.value;
  const vmin = $("#fltValorMin")?.value;
  const di = $("#fltDataIni")?.value;
  const df = $("#fltDataFim")?.value;
  if(mod) p.set("modalidade", mod);
  if(org) p.set("orgao", org);
  if(vmin) p.set("valor_min", vmin);
  if(di) p.set("data_ini", di);
  if(df) p.set("data_fim", df);
  return {min, qt, qs:p.toString()};
}
async function renderRanking(){
  const {min, qs} = rankingParams();
  const note=$("#rankNote"), list=$("#rankList");
  note.textContent = "// consultando…";
  try{
    const data = await getJSON(`/api/ranking?${qs}`);
    const sup = data.suppliers;
    note.textContent = `// ${data.count} fornecedor${data.count!==1?"es":""} com nível ≥ ${min}`
      + (data.filtro_ativo ? " · filtro ativo (recorte de contratos; nível reflete o histórico completo)" : "");
    list.innerHTML = sup.length
      ? sup.map(supCardHTML).join("")
      : `<div class="noresult">Nenhum fornecedor com nível ≥ ${min} para este recorte. Diminua o filtro.</div>`;
  }catch(err){
    note.textContent = "// erro ao consultar o ranking";
    list.innerHTML = `<div class="noresult">Não foi possível carregar o ranking (${err.message}).</div>`;
  }
}

/* ================= BUSCA (dados reais) ================= */
async function runSearch(){
  const q=$("#searchInput").value.trim();
  const box=$("#searchResults");
  if(!q){box.innerHTML="";return;}
  box.innerHTML=`<div class="skeleton"><div class="sk sk-block" style="height:56px"></div><div class="sk sk-block" style="height:56px"></div></div>`;
  try{
    const data = await getJSON(`/api/busca?q=${encodeURIComponent(q)}`);
    const partes=[];
    data.fornecedores.forEach((s,i)=>partes.push(`
      <button class="result" data-profile="${s.cnpj}" style="animation-delay:${i*60}ms">
        ${meterHTML(s.lvl)}
        <div><div class="r-name">${esc(s.name)}</div><div class="r-cnpj">${fmtCNPJ(s.cnpj)}</div></div>
        <span class="r-go">abrir perfil →</span>
      </button>`));
    data.pessoas.forEach((p,i)=>{
      const e0=p.empresas[0];
      if(!e0) return;
      partes.push(`
        <button class="result" data-profile="${e0.cnpj}" style="animation-delay:${i*60}ms">
          <span class="chip amber" style="align-self:center">sócio</span>
          <div><div class="r-name">${esc(p.nome)}</div>
            <div class="r-cnpj">${p.empresas.length} empresa${p.empresas.length!==1?"s":""} fornecedora${p.empresas.length!==1?"s":""} · ${fmtBRL(p.empresas.reduce((a,e)=>a+(e.valor||0),0))}</div></div>
          <span class="r-go">abrir 1ª empresa →</span>
        </button>`);
    });
    box.innerHTML = partes.length ? partes.join("")
      : `<div class="noresult">Nada encontrado para “<b>${esc(q)}</b>”. Tente parte do nome, o CNPJ (14 dígitos) ou o CPF do sócio.</div>`;
  }catch(err){
    box.innerHTML = `<div class="noresult">Erro na busca (${err.message}).</div>`;
  }
}

/* ================= CONTRATOS (dados reais) ================= */
let CONTRATOS_CACHE = [];
async function loadContracts(){
  const wrap=$("#contractsWrap");
  try{
    const data = await getJSON("/api/contratos?limite=200");
    CONTRATOS_CACHE = data.contratos;
    rebuildContractsTable();
    renderContracts($("#contractFilter").value);
  }catch(err){
    wrap.innerHTML = `<div class="noresult">Não foi possível carregar os contratos (${err.message}).</div>`;
  }
}
function renderContracts(filter=""){
  const q=filter.trim().toLowerCase();
  const rows=CONTRATOS_CACHE.filter(c=>!q
    || (c.orgao||"").toLowerCase().includes(q)
    || (c.modalidade||"").toLowerCase().includes(q)
    || (c.objeto||"").toLowerCase().includes(q)
    || (c.fornecedor||"").toLowerCase().includes(q));
  const body=$("#contractsBody");
  if(!body) return;
  body.innerHTML = rows.map(c=>`
    <tr>
      <td class="mono">${fmtData(c.data)}</td>
      <td>${esc(c.orgao)||"—"}<div class="sup-cnpj" style="margin-top:3px">${esc((c.objeto||"").slice(0,70))}</div></td>
      <td><span class="modalidade">${esc(c.modalidade)||"—"}</span></td>
      <td class="val" style="text-align:right">${fmtBRL(c.valor)}</td>
    </tr>`).join("") || `<tr><td colspan="4" style="color:var(--txt-2)">Nenhum contrato encontrado para “${esc(filter)}”.</td></tr>`;
  $("#contractNote").textContent = `// exibindo ${rows.length} de ${CONTRATOS_CACHE.length} contratos (200 mais recentes · PNCP/TCE-SP)`;
}
function rebuildContractsTable(){
  $("#contractsWrap").innerHTML = `<table>
    <thead><tr><th>Data</th><th>Órgão / objeto</th><th>Modalidade</th><th style="text-align:right">Valor</th></tr></thead>
    <tbody id="contractsBody"></tbody></table>`;
}

/* ================= PERFIL (dados reais via dossiê) ================= */
async function renderProfile(cnpj){
  const box=$("#profileBody");
  if(!cnpj){box.innerHTML=`<div class="noresult">Escolha um fornecedor no ranking ou na busca.</div>`;return;}
  let s;
  try{ s = await getJSON(`/api/perfil/${cnpj}`); }
  catch(err){ box.innerHTML=`<div class="noresult">Não foi possível carregar o perfil (${err.message}).</div>`; return; }

  const money = s.money.length ? s.money : [];
  const maxM = money.length ? Math.max(...money.map(m=>Math.abs(m[1]||0)),1) : 1;
  const C=2*Math.PI*50, off=C-(Math.min(s.lvl,9)/9)*C;
  const anos = Object.keys(s.valor_por_ano||{}).sort();

  box.innerHTML = `
    <div class="profile-head reveal">
      <div>
        <div class="eyebrow" style="margin-bottom:12px">Perfil do fornecedor</div>
        <div class="p-name">${esc(s.name)}</div>
        <div class="tagrow">
          <button class="cnpjtag" data-copy="${s.cnpj}" title="Copiar CNPJ">${fmtCNPJ(s.cnpj)} <span aria-hidden="true">⧉</span></button>
          <span class="chip" style="color:var(--txt-2);border-color:var(--line-2)">${esc(s.cad.cidade)}</span>
          <span class="chip" style="color:var(--txt-2);border-color:var(--line-2)">${s.n_contratos} contrato${s.n_contratos!==1?"s":""}</span>
        </div>
      </div>
      <div class="gauge" style="--gc:${lvlColor(s.lvl)}" role="img" aria-label="Nível de atenção ${s.lvl}">
        <svg width="118" height="118" viewBox="0 0 118 118">
          <circle class="track" cx="59" cy="59" r="50" fill="none" stroke-width="9"/>
          <circle class="bar" cx="59" cy="59" r="50" fill="none" stroke-width="9" stroke-dasharray="${C}" stroke-dashoffset="${C}"/>
        </svg>
        <div class="gauge-txt"><b style="color:${lvlColor(s.lvl)}">${s.lvl}</b><span>atenção</span></div>
      </div>
    </div>

    ${(s.flags_detail&&s.flags_detail.length) ? `<div style="margin-bottom:8px">`+s.flags_detail.map((fd,i)=>{
        const fl=FLAGS[fd.code]||{label:fd.code,desc:""};
        return `<div class="flagcard" style="animation-delay:${.12+i*.08}s">
          <div class="fc-ico" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg></div>
          <div><div class="fc-title">${esc(fl.label)} <span style="color:var(--txt-3);font-weight:400">(+${fd.peso})</span></div>
            <div class="fc-desc">${esc(fd.desc||fl.desc)}</div><div class="fc-code">// ${esc(fd.code)}</div></div>
        </div>`;}).join("")+`</div>`
      : `<div class="noresult reveal">Nenhuma bandeira de atenção encontrada para este fornecedor.</div>`}

    <div class="grid2">
      <div class="panel reveal" style="animation-delay:.2s">
        <h3>Cadastro <small>RECEITA FEDERAL</small></h3>
        <dl class="dl">
          <dt>situação</dt><dd class="${s.cad.situacao!=="ATIVA"?"bad":""}">${esc(s.cad.situacao)}${s.cad.especial?` / ${esc(s.cad.especial)}`:""}</dd>
          <dt>abertura</dt><dd>${fmtData(s.cad.abertura)}</dd>
          <dt>natureza</dt><dd>${esc(s.cad.natureza)}</dd>
          <dt>porte</dt><dd>${esc(s.cad.porte)}</dd>
          <dt>município</dt><dd>${esc(s.cad.cidade)}</dd>
        </dl>
      </div>
      <div class="panel reveal" style="animation-delay:.28s">
        <h3>Dinheiro recebido <small>TCE-SP</small></h3>
        ${money.length ? money.map(([ev,v])=>`
          <div class="moneyrow">
            <div class="mr-top"><span>${esc(ev)}</span><b>${fmtBRL(Math.abs(v))}${v<0?" (−)":""}</b></div>
            <div class="mbar"><i class="${v<0?"neg":""}" data-w="${Math.round(Math.abs(v)/maxM*100)}"></i></div>
          </div>`).join("") : `<p style="color:var(--txt-2);font-size:13px">Sem despesas registradas (TCE-SP) para este CNPJ.</p>`}
        ${anos.length ? `<div style="margin-top:14px;font-family:var(--mono);font-size:11px;color:var(--txt-3)">por ano: ${anos.map(a=>`${a} ${fmtBRL(s.valor_por_ano[a])}`).join(" · ")}</div>`:""}
      </div>
    </div>

    ${s.sancoes.length ? `<div class="panel reveal" style="margin-top:14px;border-color:rgba(255,97,97,.3)">
      <h3 style="color:var(--red)">Sanções <small>CEIS/CNEP</small></h3>
      ${s.sancoes.map(x=>`<div class="fc-desc">• <b>${esc(x.fonte)}</b> — ${esc(x.categoria)||"—"} <span class="fc-code">[${esc(x.vinculo)}]</span></div>`).join("")}
    </div>`:""}

    ${s.irmas.length ? `<div class="panel reveal" style="margin-top:14px">
      <h3>Rede societária <small>EMPRESAS IRMÃS</small></h3>
      ${s.irmas.map(p=>`<div class="fc-desc">• <button class="cnpjtag" data-profile="${p.cnpj}" style="cursor:pointer">${esc((p.nome||"").slice(0,40))}</button> — ${fmtBRL(p.valor)} <span class="fc-code">sócio: ${esc(p.socio)}</span></div>`).join("")}
    </div>`:""}

    ${s.contratos.length ? `<div class="panel reveal" style="margin-top:14px">
      <h3>Contratos <small>${s.n_contratos} NO TOTAL · ${s.contratos.length} EXIBIDOS</small></h3>
      <div class="tablewrap">
        <table><thead><tr><th>Data</th><th>Órgão</th><th>Modalidade</th><th style="text-align:right">Valor</th></tr></thead>
        <tbody>${s.contratos.map(c=>`<tr><td class="mono">${fmtData(c.data)}</td><td>${esc(c.orgao)||"—"}<div class="sup-cnpj" style="margin-top:3px">${esc((c.objeto||"").slice(0,60))}</div></td><td><span class="modalidade">${esc(c.modalidade)||"—"}</span></td><td class="val" style="text-align:right">${fmtBRL(c.valor)}</td></tr>`).join("")}</tbody></table>
      </div>
    </div>`:""}

    ${s.socios.length ? `<div class="panel reveal" style="margin-top:14px">
      <h3>Sócios <small>QSA</small></h3>
      ${s.socios.map(x=>`<div class="fc-desc">• ${esc(x.nome)} <span class="fc-code">${esc(x.qualificacao)||"—"} (${esc(x.tipo)||"—"})</span></div>`).join("")}
    </div>`:""}

    <div style="display:flex;gap:10px;margin-top:22px;flex-wrap:wrap">
      <a class="btn btn-ghost" href="/dossie/${s.cnpj}" target="_blank" rel="noopener">↗ Abrir dossiê completo</a>
      <button class="btn btn-ghost" data-copy="${s.cnpj}">⧉ Copiar CNPJ</button>
    </div>

    <div class="disclaimer" style="margin-top:22px">// indícios sujeitos a apuração — nunca veredito. Cada dado remete à sua fonte oficial.</div>`;

  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    const bar=$("#profileBody .bar"); if(bar) bar.style.strokeDashoffset = off;
    $$("#profileBody .mbar i").forEach(b=>b.style.width=b.dataset.w+"%");
  }));
}

/* ================= NAV ================= */
let currentProfile = null;
function nav(id){
  $$(".screen").forEach(s=>s.classList.remove("active"));
  $("#scr-"+id).classList.add("active");
  $$("[data-nav]").forEach(b=>{
    if(!b.classList.contains("navitem")) return;
    if(b.dataset.nav===id) b.setAttribute("aria-current","page");
    else b.removeAttribute("aria-current");
  });
  window.scrollTo({top:0,behavior:reduced?"auto":"smooth"});
  if(id==="ranking") withSkeleton($("#rankList"), renderRanking);
  if(id==="contratos") withSkeleton($("#contractsWrap"), loadContracts, 400);
  if(id==="perfil") withSkeleton($("#profileBody"), ()=>renderProfile(currentProfile), 500);
}

/* ================= EVENTS ================= */
document.addEventListener("click",e=>{
  const navBtn=e.target.closest("[data-nav]");
  if(navBtn){nav(navBtn.dataset.nav);return;}
  const prof=e.target.closest("[data-profile]");
  if(prof){currentProfile=prof.dataset.profile;nav("perfil");return;}
  const cp=e.target.closest("[data-copy]");
  if(cp){navigator.clipboard?.writeText(cp.dataset.copy);toast("CNPJ copiado");return;}
  if(e.target.closest("#openGloss")||e.target.closest("#openGloss2")){openModal();return;}
  if(e.target.closest("[data-close]")) closeModal();
});

/* search */
$("#searchForm").addEventListener("submit",e=>{e.preventDefault();runSearch();});

/* ranking controls */
const range=$("#lvlRange");
function syncRange(){
  range.style.setProperty("--fill",((range.value-1)/8*100)+"%");
  $("#lvlOut").textContent=range.value;
}
range.addEventListener("input",()=>{syncRange();renderRanking();});
$$(".seg button").forEach(b=>b.addEventListener("click",()=>{
  $$(".seg button").forEach(x=>x.setAttribute("aria-pressed","false"));
  b.setAttribute("aria-pressed","true");renderRanking();
}));

/* ranking filters */
$("#fltAplicar")?.addEventListener("click",()=>renderRanking());
$("#fltLimpar")?.addEventListener("click",()=>{
  ["#fltModalidade","#fltOrgao","#fltValorMin","#fltDataIni","#fltDataFim"].forEach(id=>{const el=$(id);if(el)el.value="";});
  renderRanking();
});

/* contracts filter */
$("#contractFilter").addEventListener("input",e=>renderContracts(e.target.value));

/* modal + toast */
const modal=$("#glossModal");
let lastFocus=null;
function openModal(){lastFocus=document.activeElement;modal.classList.add("open");modal.querySelector(".modal-close").focus();}
function closeModal(){modal.classList.remove("open");lastFocus?.focus();}
document.addEventListener("keydown",e=>{if(e.key==="Escape"&&modal.classList.contains("open"))closeModal();});
let toastT;
function toast(msg){const t=$("#toast");t.textContent=msg;t.classList.add("show");clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove("show"),2200);}

/* ================= INIT ================= */
renderStats();
renderHomeTop();
syncRange();
renderRanking();
