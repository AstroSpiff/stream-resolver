async function jget(url) {
  const r = await fetch(url, { credentials: "omit" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function jpost(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(body || {})
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
async function jdel(url) {
  const r = await fetch(url, { method: "DELETE" });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function byId(id){ return document.getElementById(id); }

let _lists = []; // per popolare le select Xtream

// ---------------- Settings ----------------
async function loadSettings(){
  try{
    const { settings } = await jget("/admin/settings.json");
    byId("mediaflow_url").value = settings.mediaflow_url || "";
    byId("api_password").value = settings.api_password || "";
    byId("stream_resolver_url").value = settings.stream_resolver_url || "";
  }catch(e){ console.error(e); }
}
async function saveSettings(){
  const payload = {
    mediaflow_url: byId("mediaflow_url").value.trim(),
    api_password: byId("api_password").value,
    stream_resolver_url: byId("stream_resolver_url").value.trim()
  };
  const status = byId("saveStatus");
  status.textContent = "salvataggio...";
  try{
    await jpost("/admin/settings.json", payload);
    status.textContent = "ok";
    setTimeout(()=> status.textContent="", 1500);
  }catch(e){
    console.error(e);
    status.textContent = "errore";
  }
}

// ---------------- Converti una-tantum ----------------
async function convertOnce(){
  const url = byId("conv_url").value.trim();
  const mode = byId("conv_mode").value;
  if(!url){ alert("Inserisci URL"); return; }
  let r = await fetch("/admin/convert", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({ url, mode })
  });
  if(!r.ok){
    const t = await r.text();
    alert("Errore: " + t);
    return;
  }
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "playlist_convertita.m3u";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

// ---------------- Liste salvate ----------------
async function loadLists(){
  const box = byId("lists");
  box.innerHTML = "carico...";
  try{
    const { items } = await jget("/admin/playlists.json");
    _lists = items || [];
    if(!items || !items.length){ 
      box.innerHTML = "<p class='muted'>Nessuna lista salvata</p>"; 
      await populateXtreamSelects();
      return; 
    }
    box.innerHTML = "";
    for(const it of items){
      const row = document.createElement("div");
      row.className = "row";

      const link = new URL(`./lists/${it.id}.m3u`, location.href).href;

      row.innerHTML = `
        <div class="row-main">
          <div><b>${it.name}</b></div>
          <div class="muted">${it.url}</div>
          <div>Tipo: <b>${it.mode}</b> &nbsp; • &nbsp; Aggiorna ogni
            <input class="hrs" type="number" min="1" value="${it.every_hours}"/> ore
          </div>
          <div class="muted">Ultimo refresh: ${it.last_refresh ? new Date(it.last_refresh*1000).toLocaleString() : "mai"}</div>
        </div>
        <div class="row-ops">
          <button class="small" data-act="refresh">Aggiorna</button>
          <button class="small" data-act="edit">Modifica</button>
          <button class="small" data-act="copy">Copia link</button>
          <button class="small danger" data-act="del">Elimina</button>
        </div>
      `;
      row.querySelector('[data-act="refresh"]').onclick = async ()=>{
        const hrs = parseInt(row.querySelector(".hrs").value,10)||12;
        await jpost(`/admin/playlists/${it.id}/update`, { every_hours: hrs, refresh: true });
        await loadLists();
        await populateXtreamSelects();
      };
      row.querySelector('[data-act="edit"]').onclick = async ()=>{
        const name = prompt("Nuovo nome", it.name);
        if(!name) return;
        const url = prompt("Nuovo URL", it.url) || it.url;
        await jpost(`/admin/playlists/${it.id}/update`, { name, url });
        await loadLists();
        await populateXtreamSelects();
      };
      row.querySelector('[data-act="del"]').onclick = async ()=>{
        if(!confirm("Eliminare questa lista?")) return;
        await jdel(`/admin/playlists/${it.id}`);
        await loadLists();
        await populateXtreamSelects();
      };
      row.querySelector('[data-act="copy"]').onclick = async ()=>{
        try{
          await navigator.clipboard.writeText(link);
          alert("Link copiato:\n" + link);
        }catch(e){
          const ta = document.createElement("textarea");
          ta.value = link;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand("copy");
          ta.remove();
          alert("Link copiato (fallback):\n" + link);
        }
      };
      box.appendChild(row);
    }
    await populateXtreamSelects();
  }catch(e){
    console.error(e);
    box.innerHTML = "<p class='muted'>Errore nel caricare le liste</p>";
  }
}

async function addList(){
  const name = byId("pl_name").value.trim();
  const url = byId("pl_url").value.trim();
  const mode = byId("pl_mode").value;
  const every_hours = parseInt(byId("pl_every").value,10) || 12;
  if(!name || !url){ alert("Compila nome e url"); return; }
  try{
    await jpost("/admin/playlists", { name, url, mode, every_hours });
    byId("pl_name").value = "";
    byId("pl_url").value = "";
    await loadLists();
  }catch(e){
    console.error(e);
    alert("Errore nel creare la lista");
  }
}

// ---------------- Xtream: helpers UI ----------------
function canonicalServerBase(){
  let base = (byId("stream_resolver_url").value || "").trim();
  if(!base) base = location.origin;
  if(!/^https?:\/\//i.test(base)) base = "http://" + base;
  return base.replace(/\/$/, "");
}
function optsForSelect(arr){
  return arr.map(o=>`<option value="${o.id}">${o.name}</option>`).join("");
}
async function populateXtreamSelects(){
  const live = _lists.filter(x=>x.mode==="tv");
  const vod  = _lists.filter(x=>x.mode==="video");
  const selLive   = byId("xt_live");
  const selMovies = byId("xt_movies");
  const selSeries = byId("xt_series");
  const selMixed  = byId("xt_mixed");
  if(selLive)   selLive.innerHTML   = optsForSelect(live);
  if(selMovies) selMovies.innerHTML = optsForSelect(vod);
  if(selSeries) selSeries.innerHTML = optsForSelect(vod);
  if(selMixed)  selMixed.innerHTML  = optsForSelect(vod); // miste: in genere sono 'video'
}
function valuesFromSelect(sel){
  return Array.from(sel.selectedOptions).map(o=>o.value);
}
function buildServerUrl(x){
  const base = canonicalServerBase();
  return base + "/xtream/" + x.id;
}
function buildFullM3UUrl(x){
  return (
    buildServerUrl(x) +
    "/get.php?username=" + encodeURIComponent(x.username) +
    "&password=" + encodeURIComponent(x.password) +
    "&type=m3u&output=ts"
  );
}

// ---------------- Xtream: CRUD ----------------
async function addXtream(){
  const name = byId("xt_name").value.trim();
  const username = byId("xt_user").value.trim();
  const password = byId("xt_pass").value;
  const every_hours = parseInt(byId("xt_every").value,10) || 12;
  const live_list_ids   = valuesFromSelect(byId("xt_live"));
  const movie_list_ids  = valuesFromSelect(byId("xt_movies"));
  const series_list_ids = valuesFromSelect(byId("xt_series"));
  const mixed_list_ids  = valuesFromSelect(byId("xt_mixed"));
  if(!name || !username || !password){ alert("Compila nome, username e password"); return; }
  try{
    await jpost("/admin/xtreams", { name, username, password, every_hours, live_list_ids, movie_list_ids, series_list_ids, mixed_list_ids });
    byId("xt_name").value = "";
    byId("xt_user").value = "";
    byId("xt_pass").value = "";
    await loadXtreams();
  }catch(e){
    alert("Errore: " + e.message);
  }
}

async function loadXtreams(){
  const box = byId("xtreams");
  if(!box){ return; }
  box.innerHTML = "carico...";
  try{
    const { items } = await jget("/admin/xtreams.json");
    if(!items || !items.length){ 
      box.innerHTML = "<p class='muted'>Nessun xtream salvato</p>"; 
      return; 
    }
    box.innerHTML = "";
    for(const x of items){
      const row = document.createElement("div");
      row.className = "row";
      const serverUrl = buildServerUrl(x);
      const fullUrl = buildFullM3UUrl(x);
      row.innerHTML = `
        <div class="row-main">
          <div><b>${x.name}</b></div>
          <div>Server: <code>${serverUrl}</code></div>
          <div class="muted">Utente: <b>${x.username}</b> • Password: <b>${x.password}</b> • Aggiorna ogni <input class="hrs" type="number" min="1" value="${x.every_hours}"/> ore</div>
          <div class="muted">Ultimo refresh: ${x.last_refresh ? new Date(x.last_refresh*1000).toLocaleString() : "mai"}</div>
        </div>
        <div class="row-ops">
          <button class="small" data-act="refresh">Aggiorna</button>
          <button class="small" data-act="edit">Modifica</button>
          <button class="small" data-act="copy-server">Copia URL server</button>
          <button class="small" data-act="copy-full">Copia URL completa</button>
          <button class="small danger" data-act="del">Elimina</button>
        </div>
      `;
      row.querySelector('[data-act="refresh"]').onclick = async ()=>{
        const hrs = parseInt(row.querySelector(".hrs").value,10)||12;
        await jpost(`/admin/xtreams/${x.id}/update`, { every_hours: hrs, refresh: true });
        await loadXtreams();
      };
      row.querySelector('[data-act="edit"]').onclick = async ()=>{
        const name = prompt("Nome", x.name);
        if(!name) return;
        const username = prompt("Username", x.username) || x.username;
        const password = prompt("Password", x.password) || x.password;
        const live = prompt("ID playlist Live (separate da virgola)", x.live_list_ids.join(",")) || x.live_list_ids.join(",");
        const movie = prompt("ID playlist Film (separate da virgola)", x.movie_list_ids.join(",")) || x.movie_list_ids.join(",");
        const series = prompt("ID playlist Serie (separate da virgola)", x.series_list_ids.join(",")) || x.series_list_ids.join(",");
        const mixed = prompt("ID playlist Miste (separate da virgola)", x.mixed_list_ids.join(",")) || x.mixed_list_ids.join(",");
        await jpost(`/admin/xtreams/${x.id}/update`, {
          name,
          username,
          password,
          live_list_ids: live.split(",").map(s=>s.trim()).filter(Boolean),
          movie_list_ids: movie.split(",").map(s=>s.trim()).filter(Boolean),
          series_list_ids: series.split(",").map(s=>s.trim()).filter(Boolean),
          mixed_list_ids: mixed.split(",").map(s=>s.trim()).filter(Boolean)
        });
        await loadXtreams();
      };
      row.querySelector('[data-act="del"]').onclick = async ()=>{
        if(!confirm("Eliminare questo xtream?")) return;
        await jdel(`/admin/xtreams/${x.id}`);
        await loadXtreams();
      };
      row.querySelector('[data-act="copy-server"]').onclick = async ()=>{
        const s = serverUrl;
        try{ await navigator.clipboard.writeText(s); alert("Copiato: " + s); }
        catch(e){
          const ta = document.createElement("textarea"); ta.value=s; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); alert("Copiato (fallback): " + s);
        }
      };
      row.querySelector('[data-act="copy-full"]').onclick = async ()=>{
        const s = fullUrl;
        try{ await navigator.clipboard.writeText(s); alert("Copiato: " + s); }
        catch(e){
          const ta = document.createElement("textarea"); ta.value=s; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); alert("Copiato (fallback): " + s);
        }
      };
      box.appendChild(row);
    }
  }catch(e){
    console.error(e);
    box.innerHTML = "<p class='muted'>Errore nel caricare gli xtream</p>";
  }
}

// ---------------- Boot ----------------
document.addEventListener("DOMContentLoaded", ()=>{
  byId("btnSave").onclick = saveSettings;
  byId("btnConvert").onclick = convertOnce;
  byId("btnAdd").onclick = addList;
  const btnAddXt = byId("btnAddXtream");
  if(btnAddXt) btnAddXt.onclick = addXtream;
  loadSettings().then(async ()=>{
    await loadLists();
    await loadXtreams();
  });
});
