from src.services import batches,mappings,runs,branch
from src.services.audit import log
def save_batch(data,user,item_id=None):
 row=batches.save(data,item_id);log(user.email,'batch.save',row['name']);return row
def save_mapping(data,user,item_id=None):
 row=mappings.save(data,item_id);log(user.email,'mapping.save',row['name']);return row
def start_run(data,user):
 row=runs.create(data);log(user.email,'run.queue',row['name']);return row
def register_branch(data,user):
 row=branch.register(data,user.email);log(user.email,'branch.register',f"{row['branch_code']}#{row['original_run_id']}");return row
def intake_batch(data,user):
 row=branch.intake(data,user.email);log(user.email,'branch.intake',f"{row['receipt']}:{row['status']}");return row
