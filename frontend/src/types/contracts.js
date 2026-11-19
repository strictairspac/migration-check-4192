/** @typedef {{id:number,name:string,source_file:string,rows:object[]}} Batch */
/** @typedef {{id:number,name:string,batch_id:number,rules:object[],chunk_size:number}} Mapping */
/** @typedef {{id:number,name:string,status:'queued'|'running'|'completed'|'failed'|'cancelled',origin:'local'|'branch',branch_code:string|null,original_run_id:number|null,result:object|null}} Run */
/** @typedef {{id:number,branch_code:string,original_run_id:number,digest:string,reference:object|null,note:string}} BranchRegistration */
/** @typedef {{id:number,receipt:string,status:'accepted'|'rejected',result:object,items:object[]}} IntakeBatch */
export {};
