export const normalize=(x:unknown)=>String(x??'').trim().toUpperCase();
export function exactMatch(item:any,photos:any[]){const code=normalize(item.Sku||item.Name);const candidates=photos.filter(p=>normalize(p.code)===code);return {code,candidates,status:candidates.length===1?'matched':candidates.length>1?'duplicate_photo':'missing_photo'};}
export function moneyCents(value:unknown){if(typeof value!=='number'||!Number.isFinite(value)||value<0)return null;return Math.round(value*100);}
