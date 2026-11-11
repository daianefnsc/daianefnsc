// ---------------------------------------------------------------- utilidades
const $ = (s) => document.querySelector(s);
const hojeISO = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const hora = (ts) => new Date(ts * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const duracao = (s) => (s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}min ${Math.round(s % 60)}s`);
let cameras = [];
let abaAtual = "ao-vivo";

async function api(caminho, opcoes) {
  const r = await fetch(caminho, opcoes);
  if (r.status === 401) { mostrarLogin(); throw new Error("sem login"); }
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// --------------------------------------------------------------------- login
function mostrarLogin() {
  $("#tela-app").hidden = true;
  $("#tela-login").hidden = false;
  pararAoVivo();
}

$("#form-login").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("#erro-login").textContent = "";
  const r = await fetch("api/login", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ senha: $("#senha").value }),
  });
  if (r.ok) iniciar(); else $("#erro-login").textContent = "Senha incorreta";
});

$("#sair").addEventListener("click", async () => {
  await fetch("api/sair", { method: "POST" });
  mostrarLogin();
});

// --------------------------------------------------------------------- abas
const titulos = { "ao-vivo": "Ao vivo", eventos: "Eventos", gravacoes: "Gravações", dados: "Dados" };
document.querySelectorAll(".menu button").forEach((b) =>
  b.addEventListener("click", () => abrirAba(b.dataset.aba)));

function abrirAba(aba) {
  abaAtual = aba;
  document.querySelectorAll(".menu button").forEach((b) => b.classList.toggle("ativo", b.dataset.aba === aba));
  document.querySelectorAll(".aba").forEach((s) => (s.hidden = s.id !== `aba-${aba}`));
  $("#titulo").textContent = titulos[aba];
  if (aba === "ao-vivo") iniciarAoVivo(); else pararAoVivo();
  if (aba === "eventos") carregarEventos();
  if (aba === "gravacoes") carregarGravacoes();
  if (aba === "dados") carregarDados();
}

// ------------------------------------------------------------------ ao vivo
function montarCameras() {
  $("#grade-cameras").innerHTML = cameras.map((c) => `
    <article class="camera" id="cam-${c.id}">
      <div class="imagem">
        <img alt="${c.nome}">
        <div class="sem-sinal">Conectando…</div>
      </div>
      <div class="info"><strong>${c.nome}</strong><div class="selos"></div></div>
    </article>`).join("");
  document.querySelectorAll(".camera").forEach((el) =>
    el.addEventListener("click", () => el.classList.toggle("cheia")));
}

function iniciarAoVivo() {
  cameras.forEach((c) => {
    const img = $(`#cam-${c.id} img`);
    img.onload = () => ($(`#cam-${c.id} .sem-sinal`).hidden = true);
    img.src = `api/cameras/${c.id}/ao-vivo?t=${Date.now()}`;
  });
}

function pararAoVivo() {
  document.querySelectorAll(".camera img").forEach((img) => img.removeAttribute("src"));
}

function atualizarSelos(lista) {
  lista.forEach((c) => {
    const el = $(`#cam-${c.id} .selos`);
    if (!el) return;
    el.innerHTML =
      (c.em_movimento ? '<span class="selo mov">movimento</span>' : "") +
      (c.gravando ? '<span class="selo rec">● REC</span>' : "") +
      (c.online ? '<span class="selo on">online</span>' : '<span class="selo">offline</span>');
    const semSinal = $(`#cam-${c.id} .sem-sinal`);
    if (!c.online) { semSinal.hidden = false; semSinal.textContent = "Câmera offline"; }
  });
}

async function atualizarStatus() {
  try {
    const d = await api("api/cameras");
    atualizarSelos(d.cameras);
    $("#disco").textContent = `${d.disco.livre_gb} GB livres`;
  } catch (_) { /* ignora */ }
}

// ------------------------------------------------------------------ eventos
function preencherSelect(sel, comTodas) {
  sel.innerHTML = (comTodas ? '<option value="">Todas as câmeras</option>' : "") +
    cameras.map((c) => `<option value="${c.id}">${c.nome}</option>`).join("");
}

async function carregarEventos() {
  const params = new URLSearchParams({ dia: $("#ev-dia").value || "" });
  if ($("#ev-camera").value) params.set("camera", $("#ev-camera").value);
  const eventos = await api(`api/eventos?${params}`);
  const nome = Object.fromEntries(cameras.map((c) => [c.id, c.nome]));
  $("#lista-eventos").innerHTML = eventos.length ? eventos.map((e) => `
    <div class="evento" data-id="${e.id}" data-foto="${e.tem_foto}">
      ${e.tem_foto ? `<img loading="lazy" src="api/eventos/${e.id}/foto" alt="">` : '<span class="sem-foto">foto apagada</span>'}
      <div><strong>${hora(e.inicio)}</strong>${nome[e.camera] || e.camera} · ${e.fim ? duracao(e.duracao) : "agora"}</div>
    </div>`).join("") : '<p class="vazio">Nenhum movimento neste dia 🎉</p>';
}

$("#lista-eventos").addEventListener("click", (e) => {
  const card = e.target.closest(".evento");
  if (!card || card.dataset.foto !== "true") return;
  $("#visor img").src = `api/eventos/${card.dataset.id}/foto`;
  $("#visor").hidden = false;
});
$("#visor").addEventListener("click", () => ($("#visor").hidden = true));
$("#ev-camera").addEventListener("change", carregarEventos);
$("#ev-dia").addEventListener("change", carregarEventos);

// ---------------------------------------------------------------- gravações
async function carregarGravacoes() {
  const cam = $("#gr-camera").value;
  if (!cam) return;
  const lista = await api(`api/gravacoes?camera=${cam}&dia=${$("#gr-dia").value || ""}`);
  $("#lista-gravacoes").innerHTML = lista.length ? lista.map((g) => `
    <button class="item" data-arquivo="${g.arquivo}" ${g.gravando ? "disabled" : ""}>
      <span><strong>${hora(g.inicio)}</strong><br><span class="discreto">${g.tamanho_mb} MB</span></span>
      <span class="selos">
        ${g.eventos ? `<span class="selo mov" style="animation:none">${g.eventos} mov.</span>` : ""}
        ${g.gravando ? '<span class="selo rec">gravando</span>' : "▶"}
      </span>
    </button>`).join("") : '<p class="vazio">Nenhuma gravação neste dia</p>';
}

$("#lista-gravacoes").addEventListener("click", (e) => {
  const item = e.target.closest(".item");
  if (!item || item.disabled) return;
  document.querySelectorAll(".item").forEach((i) => i.classList.toggle("tocando", i === item));
  const player = $("#player");
  player.hidden = false;
  player.src = `api/gravacoes/${$("#gr-camera").value}/${item.dataset.arquivo}`;
  player.play();
  window.scrollTo({ top: 0, behavior: "smooth" });
});
$("#gr-camera").addEventListener("change", carregarGravacoes);
$("#gr-dia").addEventListener("change", carregarGravacoes);

// --------------------------------------------------------------------- dados
const cores = ["#e84a8a", "#4ab3e8", "#3ecf8e", "#f5b84a", "#a47cf0"];
const graficos = {};

function grafico(id, tipo, labels, datasets, empilhado) {
  if (typeof Chart === "undefined") return;
  graficos[id]?.destroy();
  graficos[id] = new Chart($(id), {
    type: tipo,
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8a91a0" } } },
      scales: {
        x: { stacked: empilhado, ticks: { color: "#8a91a0", maxRotation: 0, autoSkip: true }, grid: { display: false } },
        y: { stacked: empilhado, beginAtZero: true, ticks: { color: "#8a91a0", precision: 0 }, grid: { color: "#2a2f3a" } },
      },
    },
  });
}

async function carregarDados() {
  const d = await api(`api/estatisticas?dias=${$("#dd-dias").value}`);
  const r = d.resumo;
  $("#cartoes").innerHTML = [
    [r.hoje, "movimentos hoje"],
    [r.total, "no período"],
    [r.media_dia, "média por dia"],
    [r.hora_pico === null ? "–" : `${r.hora_pico}h`, "horário mais movimentado"],
    [`${r.minutos_movimento} min`, "tempo com movimento"],
  ].map(([n, t]) => `<div class="cartao-num"><b>${n}</b><span>${t}</span></div>`).join("");

  const ids = Object.keys(d.cameras);
  const ds = (fonte, tipo) => ids.map((id, i) => ({
    label: d.cameras[id], data: fonte[id], backgroundColor: cores[i % cores.length],
    borderColor: cores[i % cores.length], borderRadius: tipo === "bar" ? 4 : 0, tension: 0.3,
  }));
  grafico("#g-dia", "bar", d.dias.map((x) => x.slice(8, 10) + "/" + x.slice(5, 7)), ds(d.por_dia, "bar"), true);
  grafico("#g-hora", "bar", [...Array(24).keys()].map((h) => `${h}h`), ds(d.por_hora, "bar"), true);
  grafico("#g-semana", "bar", ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"],
    [{ label: "Eventos", data: d.dia_semana, backgroundColor: cores[0], borderRadius: 4 }], false);
}
$("#dd-dias").addEventListener("change", carregarDados);

// ------------------------------------------------------------------ início
async function iniciar() {
  try {
    const d = await api("api/cameras");
    cameras = d.cameras;
  } catch (_) { return; }
  $("#tela-login").hidden = true;
  $("#tela-app").hidden = false;
  montarCameras();
  preencherSelect($("#ev-camera"), true);
  preencherSelect($("#gr-camera"), false);
  $("#ev-dia").value = $("#gr-dia").value = hojeISO();
  abrirAba(abaAtual);
  atualizarStatus();
}

setInterval(() => { if (!$("#tela-app").hidden) atualizarStatus(); }, 3000);
// economiza internet: para o vídeo ao vivo quando o app vai para segundo plano
document.addEventListener("visibilitychange", () => {
  if ($("#tela-app").hidden || abaAtual !== "ao-vivo") return;
  document.hidden ? pararAoVivo() : iniciarAoVivo();
});
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
iniciar();
