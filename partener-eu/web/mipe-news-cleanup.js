(()=>{
const D=window.PARTENER_DATA;
if(!D||!Array.isArray(D.calls)||!Array.isArray(D.__mipeNewsPseudoIds))return;
const ids=new Set(D.__mipeNewsPseudoIds);
D.calls=D.calls.filter(c=>!ids.has(c.id));
})();
