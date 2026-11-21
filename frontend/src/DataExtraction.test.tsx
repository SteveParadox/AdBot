import { describe, expect, it } from 'vitest';
import { parseDefinition } from './extractionSchema';

describe('schema editor',()=>{
 it('preserves incomplete edits without attempting to render invalid fields',()=>{
  for(const input of ['{','null','[]','{"name":"test","fields":{"name":null}}'])expect(parseDefinition(input)).toBeNull();
 });
 it('accepts editable safe field definitions',()=>{
  const value={name:'Products',version:1,fields:{name:{type:'string',method:'css',selector:'h1'}}};
  expect(parseDefinition(JSON.stringify(value))).toEqual(value);
 });
});
