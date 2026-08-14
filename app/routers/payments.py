from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Payment, PricingRule, CheckIn, ItemTypeEnum, PaymentMethodEnum
from app.schemas.schemas import (
    PaymentCreate, PaymentRead, PaymentPay,
    PricingCalculateRequest, PricingCalculateResponse, PricingRuleRead
)

router = APIRouter()

@router.get("/pricing-rules", response_model=List[PricingRuleRead])
def get_pricing_rules(db: Session = Depends(get_db)):
    """料金マスタ一覧を取得"""
    return db.query(PricingRule).all()

@router.post("/calculate", response_model=PricingCalculateResponse)
def calculate_checkin_fee(payload: PricingCalculateRequest, db: Session = Depends(get_db)):
    """時間単価×利用時間＋レンタル料金の概算計算"""
    rules = {rule.item_type: rule.price for rule in db.query(PricingRule).all()}
    
    lane_unit_price = rules.get(ItemTypeEnum.lane_time, 1000.0)
    shoes_unit_price = rules.get(ItemTypeEnum.shoes_rental, 300.0)
    ball_unit_price = rules.get(ItemTypeEnum.ball_rental, 200.0)

    lane_fee = lane_unit_price * payload.duration_hours
    shoes_fee = shoes_unit_price * payload.shoes_rental_count
    ball_fee = ball_unit_price * payload.ball_rental_count
    total_amount = lane_fee + shoes_fee + ball_fee

    return PricingCalculateResponse(
        lane_fee=lane_fee,
        shoes_fee=shoes_fee,
        ball_fee=ball_fee,
        total_amount=total_amount
    )

@router.post("", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
def create_payment(payload: PaymentCreate, db: Session = Depends(get_db)):
    """決済レコードの新規登録"""
    new_payment = Payment(
        payer_type=payload.payer_type,
        course_id=payload.course_id,
        checkin_id=payload.checkin_id,
        payment_timing=payload.payment_timing,
        amount=payload.amount,
        payment_method=payload.payment_method,
        is_paid=payload.is_paid,
        paid_at=datetime.now() if payload.is_paid else None
    )
    db.add(new_payment)
    db.commit()
    db.refresh(new_payment)
    return new_payment

@router.post("/{payment_id}/pay", response_model=PaymentRead)
def execute_payment(payment_id: int, payload: PaymentPay, db: Session = Depends(get_db)):
    """精算処理の実行 (未収・後払い状態から支払い完了への更新)"""
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="決済データが見つかりません")

    payment.payment_method = payload.payment_method
    payment.is_paid = True
    payment.paid_at = datetime.now()

    db.commit()
    db.refresh(payment)
    return payment
