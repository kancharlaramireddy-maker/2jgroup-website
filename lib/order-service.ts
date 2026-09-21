import {catalog,db,requireRole} from './commerce';
export async function submitCatalogOrder(data:any,isPublic:boolean,ip:string){
 const user=isPublic?null:await requireRole();
 if(!/^[a-zA-Z0-9-]{32,100}$/.test(data.requestId||''))throw new Error('Refresh the page and try again. 페이지를 새로 고침하세요.');
 const previous=await db().prepare('SELECT id,salesperson FROM orders WHERE request_id=?').bind(data.requestId).first<any>();
 if(previous){if(previous.salesperson!==(user?.email||'Public customer'))throw new Error('Invalid order reference.');return {id:previous.id};}
 if(!Array.isArray(data.lines)||!data.lines.length||data.lines.length>100)throw new Error('Choose 1–100 items. 품목을 1~100개 선택하세요.');
 const fields=['name','email','phone','line1','city','region','postal','country'];const address:Record<string,string>={};
 for(const key of [...fields,'line2']){const value=data.address?.[key];if(fields.includes(key)&&(typeof value!=='string'||!value.trim()))throw new Error('Complete contact and delivery fields. 연락처와 배송 정보를 입력하세요.');if(value&&String(value).length>200)throw new Error('Delivery field is too long.');address[key]=String(value||'').trim();}
 if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address.email))throw new Error('Enter a valid email. 올바른 이메일을 입력하세요.');
 const available=new Map((await catalog(true)).map(p=>[p.id,p]));const seen=new Set();let total=0;const lines=[];
 for(const line of data.lines){if(seen.has(line.id)||!Number.isInteger(line.qty)||line.qty<1||line.qty>10000)throw new Error('Invalid quantity or duplicate item.');seen.add(line.id);const p=available.get(line.id);if(!p?.canOrder||p.price===null)throw new Error('An item is unavailable. Refresh your catalog. 주문할 수 없는 품목이 있습니다.');if(p.price!==line.price)throw new Error('A price changed. Refresh and review your order. 가격이 변경되었습니다. 새로 고침 후 확인하세요.');total+=p.price*line.qty;lines.push({id:p.id,code:p.code,name:p.name,description:p.description,qty:line.qty,price:p.price,unit:p.unit});}
 if(!Number.isSafeInteger(total)||total>100000000)throw new Error('Order total requires office assistance.');
 let customerId='',customerName=String(data.shopName||address.name).trim().slice(0,200);
 if(user&&data.customerId){const customer=await db().prepare('SELECT id,name FROM customers WHERE id=? AND active=1').bind(String(data.customerId)).first<any>();if(!customer)throw new Error('Choose an active customer.');customerId=customer.id;customerName=customer.name;}
 if(isPublic){const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(ip)))).map(x=>x.toString(16).padStart(2,'0')).join('');const key='order_rate:'+Math.floor(Date.now()/3600000)+':'+hash;const rate=await db().prepare('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=CAST(CAST(settings.value AS INTEGER)+1 AS TEXT) RETURNING value').bind(key,'1').first<any>();if(Number(rate?.value)>20)throw new Error('Too many orders. Please try again later. 잠시 후 다시 시도하세요.');}
 const id='2J-'+crypto.randomUUID().replaceAll('-','').slice(0,12).toUpperCase();
 try{await db().prepare('INSERT INTO orders(id,request_id,salesperson,customer_id,customer_name,lines,address,notes,subtotal,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)').bind(id,data.requestId,user?.email||'Public customer',customerId,customerName,JSON.stringify(lines),JSON.stringify(address),String(data.notes||'').slice(0,2000),total,'submitted',new Date().toISOString()).run();}catch(error){const saved=await db().prepare('SELECT id,salesperson FROM orders WHERE request_id=?').bind(data.requestId).first<any>();if(saved?.salesperson===(user?.email||'Public customer'))return {id:saved.id};throw error;}
 return {id};
}
