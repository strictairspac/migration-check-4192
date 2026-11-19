from fastapi import APIRouter,Depends
from src.middlewares.auth import current,writer
from src.schemas.business import BranchRegistrationInput,BranchIntakeInput
from src.services import branch
from src.controllers.business import register_branch,intake_batch
router=APIRouter()
@router.get('/branches/registrations')
def registrations(u=Depends(current)):return branch.list_registrations()
@router.post('/branches/registrations')
def register(data:BranchRegistrationInput,u=Depends(writer)):return register_branch(data,u)
@router.get('/branches/intakes')
def intakes(u=Depends(current)):return branch.list_items()
@router.post('/branches/intakes')
def intake(data:BranchIntakeInput,u=Depends(writer)):return intake_batch(data,u)
@router.get('/branches/intakes/{item_id}')
def intake_detail(item_id:int,u=Depends(current)):return branch.detail(item_id)
@router.get('/branches/intakes/{item_id}/verify')
def intake_verify(item_id:int,u=Depends(current)):return branch.verify(item_id)
