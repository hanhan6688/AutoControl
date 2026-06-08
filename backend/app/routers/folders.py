"""Test case folder (document) CRUD API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ImportedTestCase, TestCaseFolder, TestPlanProject
from app.schemas import (
    TestCaseFolderCreateRequest,
    TestCaseFolderResponse,
    TestCaseFolderUpdateRequest,
)

router = APIRouter(prefix="/api/folders", tags=["test-case-folders"])


@router.post("/plans/{plan_id}/folders", response_model=TestCaseFolderResponse)
def create_folder(
    plan_id: int,
    folder_data: TestCaseFolderCreateRequest,
    db: Session = Depends(get_db),
) -> TestCaseFolder:
    """在指定测试计划下创建文档"""
    plan = db.query(TestPlanProject).filter(TestPlanProject.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="测试计划不存在")

    # 获取当前最大 sequence
    max_seq = (
        db.query(func.max(TestCaseFolder.sequence))
        .filter(TestCaseFolder.plan_id == plan_id)
        .scalar()
        or 0
    )

    folder = TestCaseFolder(
        plan_id=plan_id,
        name=folder_data.name,
        requirement_summary=folder_data.requirement_summary,
        source_type=folder_data.source_type or "manual",
        source_filename=folder_data.source_filename,
        sequence=max_seq + 1,
        total_cases=0,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.get("/plans/{plan_id}/folders", response_model=list[TestCaseFolderResponse])
def list_folders(
    plan_id: int,
    db: Session = Depends(get_db),
) -> list[TestCaseFolder]:
    """获取测试计划下的所有文档"""
    folders = (
        db.query(TestCaseFolder)
        .filter(TestCaseFolder.plan_id == plan_id)
        .order_by(TestCaseFolder.sequence)
        .all()
    )
    return folders


@router.put("/folders/{folder_id}", response_model=TestCaseFolderResponse)
def update_folder(
    folder_id: int,
    folder_data: TestCaseFolderUpdateRequest,
    db: Session = Depends(get_db),
) -> TestCaseFolder:
    """更新文档"""
    folder = db.query(TestCaseFolder).filter(TestCaseFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="文档不存在")

    if folder_data.name is not None:
        folder.name = folder_data.name
    if folder_data.requirement_summary is not None:
        folder.requirement_summary = folder_data.requirement_summary

    db.commit()
    db.refresh(folder)
    return folder


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """删除文档（连同其下所有用例）"""
    folder = db.query(TestCaseFolder).filter(TestCaseFolder.id == folder_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 更新计划的用例计数
    plan = db.query(TestPlanProject).filter(TestPlanProject.id == folder.plan_id).first()
    folder_case_count = (
        db.query(ImportedTestCase)
        .filter(ImportedTestCase.folder_id == folder_id)
        .count()
    )
    if plan and plan.total_cases is not None:
        plan.total_cases = max(0, (plan.total_cases or 0) - folder_case_count)

    db.delete(folder)
    db.commit()
    return {"message": "删除成功"}


@router.post("/cases/batch-move")
def batch_move_cases(
    data: dict,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """批量移动用例到其他文档"""
    case_ids = data.get("case_ids", [])
    target_folder_id = data.get("target_folder_id")

    if not case_ids or target_folder_id is None:
        raise HTTPException(status_code=400, detail="参数不完整")

    target_folder = db.query(TestCaseFolder).filter(TestCaseFolder.id == target_folder_id).first()
    if not target_folder:
        raise HTTPException(status_code=404, detail="目标文档不存在")

    # 获取要移动的用例
    cases = db.query(ImportedTestCase).filter(ImportedTestCase.id.in_(case_ids)).all()

    # 记录源文档ID，用于更新计数
    source_folder_ids: set[int] = set()
    for case in cases:
        if case.folder_id and case.folder_id != target_folder_id:
            source_folder_ids.add(case.folder_id)
        case.folder_id = target_folder_id

    # 更新源文档的用例计数
    for src_id in source_folder_ids:
        src_folder = db.query(TestCaseFolder).filter(TestCaseFolder.id == src_id).first()
        if src_folder:
            src_folder.total_cases = (
                db.query(ImportedTestCase)
                .filter(ImportedTestCase.folder_id == src_id)
                .count()
            )

    # 更新目标文档的用例计数
    target_folder.total_cases = (
        db.query(ImportedTestCase)
        .filter(ImportedTestCase.folder_id == target_folder_id)
        .count()
    )

    db.commit()
    return {"message": f"已移动 {len(cases)} 条用例"}
