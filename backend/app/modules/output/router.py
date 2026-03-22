"""Output router - API endpoints (simplified)"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_operator_ref
from app.modules.output.service import output_service_obj
from app.modules.output.schemas import (
    OutputCreateRequest,
    OutputCreateResponse,
    OutputListResponse,
    OutputResponse,
    OutputConfirmRequest,
    OutputConfirmResponse,
    OutputAdoptRequest,
    OutputAdoptResponse,
)
from app.common.responses import success_response


router = APIRouter(tags=["Output"])

@router.post("/items/{item_id}/outputs", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_output(
    item_id: int,
    request: OutputCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate Output"""
    output = await output_service_obj.create(
        db=db,
        item_id=item_id,
        output_type=request.output_type,
        analysis_id=request.analysis_id,
    )
    return success_response(
        data=OutputCreateResponse.model_validate(output),
        message="Output generated",
        code=201,
    )

@router.get("/items/{item_id}/outputs", response_model=dict)
async def get_item_outputs(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """List all Outputs for an Item"""
    from app.modules.output.repository import output_repository
    outputs = await output_repository.list_by_item_id(db, item_id)
    return success_response(
        data=[OutputListResponse.model_validate(o) for o in outputs],
        message="Success",
    )

@router.get("/outputs/{output_id}", response_model=dict)
async def get_output(
    output_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get Output details"""
    from app.modules.output.repository import output_repository
    output = await output_repository.get_by_id(db, output_id)
    if not output:
        from app.core.exceptions import NotFoundException
        raise NotFoundException(f"Output {output_id} not found")
    return success_response(
        data=OutputResponse.model_validate(output),
        message="Success",
    )

@router.post("/outputs/{output_id}/confirm", response_model=dict)
async def confirm_output(
    output_id: int,
    request: OutputConfirmRequest,
    db: AsyncSession = Depends(get_db),
    operator_ref: str = Depends(get_operator_ref),
):
    """Confirm Output"""
    output = await output_service_obj.confirm(db=db, output_id=output_id)
    return success_response(
        data=OutputConfirmResponse.model_validate(output),
        message="Output confirmed",
    )

@router.post("/outputs/{output_id}/adopt", response_model=dict)
async def adopt_output(
    output_id: int,
    request: OutputAdoptRequest,
    db: AsyncSession = Depends(get_db),
    operator_ref: str = Depends(get_operator_ref),
):
    """Adopt Output"""
    output = await output_service_obj.adopt(
        db=db,
        output_id=output_id,
        adopted_target=request.adopted_target,
    )
    return success_response(
        data=OutputAdoptResponse.model_validate(output),
        message="Output adopted",
    )
