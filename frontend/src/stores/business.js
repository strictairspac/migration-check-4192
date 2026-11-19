import {batches,mappings,runs,branches} from '../api/business.js';
export const store={batches:[],mappings:[],runs:[],registrations:[],intakes:[],user:null};
export async function refresh(){[store.batches,store.mappings,store.runs,store.registrations,store.intakes]=await Promise.all([batches.list(),mappings.list(),runs.list(),branches.registrations(),branches.intakes()]);}
