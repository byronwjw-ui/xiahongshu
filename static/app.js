// Shared frontend logic for 小红书 generator (index, settings, admin).
const TOKEN_KEY = 'xhs_token';
function getToken(){return localStorage.getItem(TOKEN_KEY)||''}
function setToken(t){localStorage.setItem(TOKEN_KEY,t)}
function clearToken(){localStorage.removeItem(TOKEN_KEY)}

function toast(msg){
  const t=document.getElementById('toast');if(!t)return;
  t.textContent=msg;t.classList.add('show');
  clearTimeout(window.__toastT);
  window.__toastT=setTimeout(()=>t.classList.remove('show'),1800);
}

async function api(path,opts={}){
  const headers={'Content-Type':'application/json',...(opts.headers||{})};
  const tok=getToken();if(tok)headers['Authorization']='Bearer '+tok;
  if(opts.body&&!(opts.body instanceof FormData))opts.body=JSON.stringify(opts.body);
  if(opts.body instanceof FormData)delete headers['Content-Type'];
  const r=await fetch(path,{...opts,headers});
  let data={};try{data=await r.json()}catch{}
  if(!r.ok){
    if(r.status===401){clearToken();location.href='/';return}
    if(data.redirect){toast(data.error||'需要设置 API Key');setTimeout(()=>location.href=data.redirect,1200);throw new Error(data.error)}
    toast(data.error||('HTTP '+r.status));throw new Error(data.error||r.status);
  }
  return data;
}

function copyText(s){navigator.clipboard.writeText(s).then(()=>toast('已复制'))}

// ============ INDEX (main app) =================================================
async function initApp(){
  const auth=document.getElementById('auth'),appEl=document.getElementById('app');
  if(!auth||!appEl)return;
  if(!getToken()){auth.style.display='flex';bindAuth();return}
  try{
    const {user}=await api('/api/me');
    auth.style.display='none';appEl.style.display='block';
    document.getElementById('who').textContent=user.email+(user.role==='admin'?' (admin)':'');
    if(user.role==='admin')document.getElementById('adminLink').style.display='inline-block';
    bindMain();loadPosts();
  }catch{auth.style.display='flex';bindAuth()}
}

function bindAuth(){
  document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{
    document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
    document.getElementById('login-form').style.display=b.dataset.tab==='login'?'block':'none';
    document.getElementById('register-form').style.display=b.dataset.tab==='register'?'block':'none';
  });
  document.getElementById('btn-login').onclick=async()=>{
    const email=document.getElementById('login-email').value.trim();
    const password=document.getElementById('login-pass').value;
    const d=await api('/api/login',{method:'POST',body:{email,password}});
    setToken(d.token);location.reload();
  };
  document.getElementById('btn-register').onclick=async()=>{
    const email=document.getElementById('reg-email').value.trim();
    const password=document.getElementById('reg-pass').value;
    await api('/api/register',{method:'POST',body:{email,password}});
    toast('验证码已发送 (查看服务器控制台 / mail.log)');
    document.getElementById('reg-code').style.display='block';
    document.getElementById('btn-verify').style.display='block';
  };
  document.getElementById('btn-verify').onclick=async()=>{
    const email=document.getElementById('reg-email').value.trim();
    const code=document.getElementById('reg-code').value.trim();
    const d=await api('/api/verify',{method:'POST',body:{email,code}});
    setToken(d.token);location.reload();
  };
}

let currentPost={id:null,images:[]};
let outputA=null;

function bindMain(){
  document.getElementById('btn-logout').onclick=()=>{clearToken();location.reload()};
  const fileInput=document.getElementById('file');
  fileInput.onchange=async()=>{
    const f=fileInput.files[0];if(!f)return;
    document.getElementById('fileName').textContent=f.name+' (解析中...)';
    const fd=new FormData();fd.append('file',f);
    try{
      const r=await api('/api/upload',{method:'POST',body:fd});
      outputA=r.output_a;
      document.getElementById('outputA').style.display='block';
      document.getElementById('outputA').textContent='提取素材: '+JSON.stringify(r.output_a).slice(0,200)+'...';
      document.getElementById('fileName').textContent=f.name+' ✅';
      toast('文件解析完成');
    }catch{document.getElementById('fileName').textContent=f.name+' ❌'}
  };
  document.getElementById('btn-gen-text').onclick=async(e)=>{
    const btn=e.target;btn.disabled=true;btn.innerHTML='<span class=spinner></span>生成中';
    try{
      const topic=document.getElementById('topic').value.trim();
      const body={};if(outputA)body.output_a=outputA;else body.topic=topic;
      if(!outputA&&!topic){toast('请输入主题或上传文件');return}
      const r=await api('/api/generate/text',{method:'POST',body});
      document.getElementById('editor').style.display='block';
      document.getElementById('imgPanel').style.display='block';
      document.getElementById('f-title').value=r.title;
      document.getElementById('f-body').value=r.body;
      document.getElementById('f-tags').value=r.hashtags.join(',');
      document.getElementById('f-prompt').value=r.image_prompt||'';
      currentPost={id:null,images:[]};
      updatePreview();
      toast('文案生成完成 ✨');
    }finally{btn.disabled=false;btn.textContent='✨ 生成文案'}
  };
  ['f-title','f-body','f-tags'].forEach(id=>document.getElementById(id).addEventListener('input',updatePreview));
  document.querySelectorAll('[data-copy]').forEach(b=>b.onclick=()=>{
    const m=b.dataset.copy;
    if(m==='title')copyText(document.getElementById('f-title').value);
    else if(m==='body')copyText(document.getElementById('f-body').value);
    else if(m==='tags')copyText(document.getElementById('f-tags').value);
    else copyText([document.getElementById('f-title').value,'',document.getElementById('f-body').value,'',document.getElementById('f-tags').value].join('\n'));
  });
  document.getElementById('btn-save').onclick=savePost;
  document.getElementById('btn-gen-img').onclick=genImages;
  document.getElementById('btn-regen-img').onclick=genImages;
}

function updatePreview(){
  document.getElementById('p-title').textContent=document.getElementById('f-title').value||'标题';
  document.getElementById('p-body').textContent=document.getElementById('f-body').value||'正文...';
  const tags=document.getElementById('f-tags').value.split(/[\s,，]+/).filter(Boolean);
  document.getElementById('p-tags').innerHTML=tags.map(t=>`<span class="xhs-chip">${t}</span>`).join('');
  const imgs=document.getElementById('p-imgs');
  if(currentPost.images&&currentPost.images.length){
    imgs.innerHTML=currentPost.images.map(u=>`<img class="phone-img" src="${u}"/>`).join('');
  }
}

async function genImages(e){
  const btn=e?.target;if(btn){btn.disabled=true;btn.innerHTML='<span class=spinner></span>生成中'}
  try{
    const prompt=document.getElementById('f-prompt').value.trim();
    const aspect_ratio=document.getElementById('f-aspect').value;
    const count=parseInt(document.getElementById('f-count').value);
    if(!prompt){toast('请填写 image prompt');return}
    const r=await api('/api/generate/image',{method:'POST',body:{prompt,aspect_ratio,count}});
    currentPost.images=r.images;
    updatePreview();
    toast('图片生成完成 🎨');
  }finally{if(btn){btn.disabled=false;btn.textContent=btn.id==='btn-regen-img'?'🔄 重新生成图片':'🎨 生成图片'}}
}

async function savePost(){
  const tags=document.getElementById('f-tags').value.split(/[\s,，]+/).filter(Boolean);
  const body={
    id:currentPost.id,
    topic:document.getElementById('topic').value,
    title:document.getElementById('f-title').value,
    body:document.getElementById('f-body').value,
    hashtags:tags,
    image_prompt:document.getElementById('f-prompt').value,
    images:currentPost.images||[],
  };
  const r=await api('/api/posts',{method:'POST',body});
  currentPost.id=r.post.id;
  toast('已保存 💾');
  loadPosts();
}

async function loadPosts(){
  const r=await api('/api/posts');
  const wrap=document.getElementById('posts');if(!wrap)return;
  wrap.innerHTML=r.posts.map(p=>`
    <div class="border border-gray-100 rounded-xl p-3 flex items-center gap-3 cursor-pointer hover:border-pink-300" data-id="${p.id}">
      <img src="${(p.images&&p.images[0])||'https://images.unsplash.com/photo-1544161515-4ab6ce6db874?w=200'}" class="w-14 h-14 object-cover rounded-lg"/>
      <div class="flex-1 min-w-0">
        <div class="font-semibold truncate">${p.title||'(无标题)'}</div>
        <div class="text-xs text-gray-500 truncate">${(p.body||'').slice(0,40)}</div>
      </div>
      <button class="text-xs text-red-500" data-del="${p.id}">删</button>
    </div>`).join('')||'<div class="text-sm text-gray-400">还没有文案</div>';
  wrap.querySelectorAll('[data-id]').forEach(el=>el.onclick=ev=>{
    if(ev.target.dataset.del)return;
    const p=r.posts.find(x=>x.id==el.dataset.id);loadIntoEditor(p);
  });
  wrap.querySelectorAll('[data-del]').forEach(el=>el.onclick=async(ev)=>{
    ev.stopPropagation();
    if(!confirm('删除此文案？'))return;
    await api('/api/posts/'+el.dataset.del,{method:'DELETE'});loadPosts();
  });
}

function loadIntoEditor(p){
  document.getElementById('editor').style.display='block';
  document.getElementById('imgPanel').style.display='block';
  document.getElementById('topic').value=p.topic||'';
  document.getElementById('f-title').value=p.title||'';
  document.getElementById('f-body').value=p.body||'';
  document.getElementById('f-tags').value=(p.hashtags||[]).join(',');
  document.getElementById('f-prompt').value=p.image_prompt||'';
  currentPost={id:p.id,images:p.images||[]};
  updatePreview();
}

// ============ SETTINGS =========================================================
window.initSettings=async function(){
  if(!getToken()){location.href='/';return}
  const k=await api('/api/keys');
  document.getElementById('text_provider').value=k.text_provider||'openai';
  document.getElementById('image_provider').value=k.image_provider||'dalle';
  document.getElementById('text_masked').textContent=k.text_set?('当前: '+k.text_key_masked):'';
  document.getElementById('image_masked').textContent=k.image_set?('当前: '+k.image_key_masked):'';
  document.getElementById('st-text').className=k.text_set?'status-ok':'status-bad';
  document.getElementById('st-text').textContent=k.text_set?'✅ 已连接':(k.system_text_fallback?'⚠️ 使用系统备用':'❌ 未设置');
  document.getElementById('st-img').className=k.image_set?'status-ok':'status-bad';
  document.getElementById('st-img').textContent=k.image_set?'✅ 已连接':(k.system_image_fallback?'⚠️ 使用系统备用':'❌ 未设置');

  document.getElementById('save-text').onclick=async()=>{
    await api('/api/keys',{method:'POST',body:{
      text_provider:document.getElementById('text_provider').value,
      text_key:document.getElementById('text_key').value,
    }});
    toast('文本密钥已保存');setTimeout(initSettings,300);
  };
  document.getElementById('save-image').onclick=async()=>{
    await api('/api/keys',{method:'POST',body:{
      image_provider:document.getElementById('image_provider').value,
      image_key:document.getElementById('image_key').value,
    }});
    toast('图片密钥已保存');setTimeout(initSettings,300);
  };
  document.getElementById('test-text').onclick=async(e)=>{
    e.target.disabled=true;e.target.textContent='测试中...';
    try{
      const r=await api('/api/keys/test',{method:'POST',body:{
        which:'text',
        text_provider:document.getElementById('text_provider').value,
        text_key:document.getElementById('text_key').value,
      }});
      toast(r.ok?'✅ 连接成功':'❌ 连接失败');
    }finally{e.target.disabled=false;e.target.textContent='🔌 测试连接'}
  };
  document.getElementById('test-image').onclick=async(e)=>{
    e.target.disabled=true;e.target.textContent='测试中...';
    try{
      const r=await api('/api/keys/test',{method:'POST',body:{
        which:'image',
        image_provider:document.getElementById('image_provider').value,
        image_key:document.getElementById('image_key').value,
      }});
      toast(r.ok?'✅ 连接成功':'❌ 连接失败');
    }finally{e.target.disabled=false;e.target.textContent='🔌 测试连接'}
  };
};

// ============ ADMIN ============================================================
window.initAdmin=async function(){
  if(!getToken()){location.href='/';return}
  try{
    const me=await api('/api/me');
    if(me.user.role!=='admin'){toast('需要管理员');setTimeout(()=>location.href='/',1000);return}
  }catch{return}
  const sk=await api('/api/admin/system-keys');
  document.getElementById('sys_text_provider').value=sk.text_provider||'openai';
  document.getElementById('sys_image_provider').value=sk.image_provider||'dalle';
  document.getElementById('sys_text_masked').textContent=sk.text_set?('当前: '+sk.text_key_masked):'';
  document.getElementById('sys_image_masked').textContent=sk.image_set?('当前: '+sk.image_key_masked):'';
  document.getElementById('save-sys').onclick=async()=>{
    await api('/api/admin/system-keys',{method:'POST',body:{
      text_provider:document.getElementById('sys_text_provider').value,
      text_key:document.getElementById('sys_text_key').value,
      image_provider:document.getElementById('sys_image_provider').value,
      image_key:document.getElementById('sys_image_key').value,
    }});
    toast('已保存');setTimeout(initAdmin,300);
  };
  const users=(await api('/api/admin/users')).users;
  document.getElementById('users-list').innerHTML=`
    <table class="w-full text-sm"><thead><tr class="text-left text-gray-500">
      <th class="py-2">Email</th><th>Role</th><th>Created</th><th>Posts</th><th>Key</th><th></th></tr></thead><tbody>
      ${users.map(u=>`<tr class="border-t">
        <td class="py-2">${u.email}</td><td>${u.role}</td>
        <td>${(u.created_at||'').slice(0,10)}</td><td>${u.post_count}</td>
        <td>${u.has_api_key?'✅':'—'}</td>
        <td>${u.role!=='admin'?`<button class="text-xs text-red-500" data-du="${u.id}">删除</button>`:''}</td>
      </tr>`).join('')}</tbody></table>`;
  document.querySelectorAll('[data-du]').forEach(b=>b.onclick=async()=>{
    if(!confirm('删除该用户？'))return;
    await api('/api/admin/users/'+b.dataset.du,{method:'DELETE'});initAdmin();
  });
  const posts=(await api('/api/admin/posts')).posts;
  document.getElementById('posts-list').innerHTML=posts.map(p=>`
    <div class="border border-gray-100 rounded-xl p-3 flex gap-3">
      <img src="${(p.images&&p.images[0])||'https://images.unsplash.com/photo-1544161515-4ab6ce6db874?w=200'}" class="w-16 h-16 object-cover rounded-lg"/>
      <div class="flex-1 min-w-0">
        <div class="font-semibold truncate">${p.title||'(无标题)'}</div>
        <div class="text-xs text-gray-500 truncate">${p.user_email||''} · ${(p.created_at||'').slice(0,10)}</div>
        <div class="text-xs text-gray-500 truncate">${(p.body||'').slice(0,50)}</div>
      </div>
      <button class="text-xs text-red-500" data-dp="${p.id}">删</button>
    </div>`).join('')||'<div class="text-sm text-gray-400">暂无文案</div>';
  document.querySelectorAll('[data-dp]').forEach(b=>b.onclick=async()=>{
    if(!confirm('删除该文案？'))return;
    await api('/api/admin/posts/'+b.dataset.dp,{method:'DELETE'});initAdmin();
  });
};

// auto-init on index
if(document.getElementById('auth'))initApp();
