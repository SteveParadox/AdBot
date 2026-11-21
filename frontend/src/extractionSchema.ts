export type Rule = {type:string;method:string;selector?:string;path?:string;required?:boolean;attribute?:string|null;[key:string]:unknown};
export type Definition = {name:string;version:number;fields:Record<string,Rule>;identity_fields?:string[];[key:string]:unknown};

export function parseDefinition(text:string):Definition|null {
 try { const value=JSON.parse(text); if(!value||typeof value!=='object'||typeof value.name!=='string'||!value.fields||typeof value.fields!=='object'||Array.isArray(value.fields))return null;
 if(!Object.values(value.fields).every(v=>v&&typeof v==='object'&&'type' in v&&'method' in v))return null;
 return value as Definition;
 } catch { return null; }
}
