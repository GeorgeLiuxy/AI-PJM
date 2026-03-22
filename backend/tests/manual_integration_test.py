"""Manual integration test for full closed loop"""

import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.db import Base, get_db
from sqlalchemy import select, text

# Import all models so SQLAlchemy can discover them
from app.modules.item.models import Item, ItemSuggestion
from app.modules.analysis.models import Analysis
from app.modules.output.models import Output
from app.modules.audit.models import ActionLog

# Test database
TEST_DATABASE_URL = 'postgresql+asyncpg://ai_pjm_user:ai_pjm_password@localhost:5432/ai_pjm_test'


async def manual_integration_test():
    """Manual integration test: full closed loop"""

    # 1. Setup database
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db = SessionLocal()

    try:
        # Override get_db to use test database
        async def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                print('=== Full Closed Loop Integration Test ===\n')

                # STEP 1: Create Item draft
                print('[1/9] Create Item draft...')
                response = await client.post('/api/v1/items/draft', json={
                    'raw_input': 'User feedback: login timeout issue',
                    'source_type': 'customer_feedback'
                })
                assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
                item_id = response.json()['data']['id']
                item_status = response.json()['data']['status']
                print(f'[OK] Item created: id={item_id}, status={item_status}')
                assert item_status == 'draft', f"Expected draft, got {item_status}"

                # STEP 2: Run AI understanding
                print('\n[2/9] Run AI understanding...')
                response = await client.post(f'/api/v1/items/{item_id}/understand', json={
                    'force_refresh': False
                })
                assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
                item_status = response.json()['data']['status']
                print(f'[OK] Item understood: status={item_status}')
                assert item_status == 'pending_confirm', f"Expected pending_confirm, got {item_status}"

                # STEP 3: Confirm Item suggestion
                print('\n[3/9] Confirm Item suggestion...')
                response = await client.post(f'/api/v1/items/{item_id}/confirm', json={
                    'confirm_mode': 'accept'
                })
                assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
                item_status = response.json()['data']['status']
                print(f'[OK] Item confirmed: status={item_status}')
                assert item_status == 'confirmed', f"Expected confirmed, got {item_status}"

                # STEP 4: Create Analysis
                print('\n[4/9] Create Analysis...')
                response = await client.post(f'/api/v1/items/{item_id}/analysis')
                assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
                analysis_id = response.json()['data']['id']
                analysis_status = response.json()['data']['status']
                print(f'[OK] Analysis created: id={analysis_id}, analysis_status={analysis_status}')
                assert analysis_status == 'pending', f"Expected pending, got {analysis_status}"

                # Verify item status changed to analyzing
                response = await client.get(f'/api/v1/items/{item_id}')
                item_status = response.json()['data']['status']
                print(f'[OK] Item status changed to: {item_status}')
                assert item_status == 'analyzing', f"Expected analyzing, got {item_status}"

                # STEP 5: Run Analysis
                print('\n[5/9] Run Analysis...')
                response = await client.post(f'/api/v1/analysis/{analysis_id}/run')
                assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
                analysis_status = response.json()['data']['status']
                print(f'[OK] Analysis running: status={analysis_status}')
                assert analysis_status == 'pending_review', f"Expected pending_review, got {analysis_status}"

                # STEP 6: Confirm Analysis
                print('\n[6/9] Confirm Analysis...')
                response = await client.post(f'/api/v1/analysis/{analysis_id}/confirm', json={
                    'final_recommendation': 'do_now'
                })
                assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
                analysis_status = response.json()['data']['status']
                print(f'[OK] Analysis confirmed: analysis_status={analysis_status}')
                assert analysis_status == 'confirmed', f"Expected confirmed, got {analysis_status}"

                # Verify item status changed to decided
                response = await client.get(f'/api/v1/items/{item_id}')
                item_status = response.json()['data']['status']
                print(f'[OK] Item status changed to: {item_status}')
                assert item_status == 'decided', f"Expected decided, got {item_status}"

                # STEP 7: Create Output
                print('\n[7/9] Create Output...')
                response = await client.post(f'/api/v1/items/{item_id}/outputs', json={
                    'output_type': 'prd',
                    'analysis_id': analysis_id
                })
                assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
                output_id = response.json()['data']['id']
                output_status = response.json()['data']['status']
                print(f'[OK] Output created: id={output_id}, output_status={output_status}')
                assert output_status == 'pending_confirm', f"Expected pending_confirm, got {output_status}"

                # Verify item status changed to output_generated
                response = await client.get(f'/api/v1/items/{item_id}')
                item_status = response.json()['data']['status']
                print(f'[OK] Item status changed to: {item_status}')
                assert item_status == 'output_generated', f"Expected output_generated, got {item_status}"

                # STEP 8: Confirm Output
                print('\n[8/9] Confirm Output...')
                response = await client.post(f'/api/v1/outputs/{output_id}/confirm', json={})
                assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
                output_status = response.json()['data']['status']
                print(f'[OK] Output confirmed: output_status={output_status}')
                assert output_status == 'confirmed', f"Expected confirmed, got {output_status}"

                # confirm does NOT change item_status
                response = await client.get(f'/api/v1/items/{item_id}')
                item_status = response.json()['data']['status']
                print(f'[OK] Item status unchanged: {item_status}')
                assert item_status == 'output_generated', f"Expected output_generated, got {item_status}"

                # STEP 9: Adopt Output
                print('\n[9/9] Adopt Output...')
                response = await client.post(f'/api/v1/outputs/{output_id}/adopt', json={
                    'adopted_target': 'formal_prd'
                })
                assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
                output_status = response.json()['data']['status']
                print(f'[OK] Output adopted: output_status={output_status}')
                assert output_status == 'adopted', f"Expected adopted, got {output_status}"

                # Verify item status changed to done
                response = await client.get(f'/api/v1/items/{item_id}')
                item_status = response.json()['data']['status']
                print(f'[OK] Item status changed to: {item_status}')
                assert item_status == 'done', f"Expected done, got {item_status}"

                print('\n' + '='*50)
                print('[PASS] Full closed loop test PASSED!')
                print('='*50)

                # Verify action_logs chain
                print('\n=== Verify action_logs chain ===')

                # Debug: Check all action_logs
                result_all = await db.execute(
                    select(ActionLog).order_by(ActionLog.id)
                )
                all_logs = result_all.scalars().all()
                print(f'Total action_logs in database: {len(all_logs)}')

                result = await db.execute(
                    select(ActionLog)
                    .where(ActionLog.biz_id == item_id)
                    .order_by(ActionLog.id)
                )
                action_logs = result.scalars().all()

                print(f'Total action_logs for item_id={item_id}: {len(action_logs)}')
                for log in action_logs:
                    print(f'  - {log.action_type}: {log.from_status} -> {log.to_status} | operator={log.operator_type}')

                # Expected action_logs for Item:
                # 1. ITEM_CREATED: None -> draft
                # 2. ITEM_UNDERSTOOD: draft -> pending_confirm
                # 3. ITEM_CONFIRMED: pending_confirm -> confirmed
                # 4. ITEM_STATUS_CHANGED_TO_ANALYZING: confirmed -> analyzing
                # 5. ITEM_STATUS_CHANGED_TO_DECIDED: analyzing -> decided
                # 6. ITEM_STATUS_CHANGED_TO_OUTPUT_GENERATED: decided -> output_generated
                # 7. ITEM_STATUS_CHANGED_TO_DONE: output_generated -> done

                expected_actions = [
                    'item_created',
                    'item_understood',
                    'item_confirmed',
                    'item_status_changed_to_analyzing',
                    'item_status_changed_to_decided',
                    'item_status_changed_to_output_generated',
                    'item_status_changed_to_done',
                ]

                actual_actions = [log.action_type for log in action_logs]
                print(f'\nExpected: {expected_actions}')
                print(f'Actual:   {actual_actions}')

                # Verify expected actions exist
                for expected in expected_actions:
                    assert expected in actual_actions, f"Missing action: {expected}"

                print('\n[PASS] action_logs chain verified!')

                # Verify final state
                print('\n=== Verify final state ===')

                # Check Item
                result = await db.execute(select(Item).where(Item.id == item_id))
                final_item = result.scalar_one_or_none()
                print(f'Final Item status: {final_item.status}')
                assert final_item.status == 'done', f"Expected done, got {final_item.status}"

                # Check Analysis
                result = await db.execute(select(Analysis).where(Analysis.item_id == item_id))
                final_analysis = result.scalar_one_or_none()
                print(f'Final Analysis status: {final_analysis.status}')
                assert final_analysis.status == 'confirmed', f"Expected confirmed, got {final_analysis.status}"

                # Check Output
                result = await db.execute(select(Output).where(Output.item_id == item_id))
                final_output = result.scalar_one_or_none()
                print(f'Final Output status: {final_output.status}')
                assert final_output.status == 'adopted', f"Expected adopted, got {final_output.status}"

                print('\n[PASS] Final state verified!')
                print('\n' + '='*50)
                print('COMPLETE INTEGRATION TEST PASSED!')
                print('='*50)
                print('\nSummary:')
                print('  [OK] Item status: draft -> done')
                print('  [OK] Analysis status: pending -> confirmed')
                print('  [OK] Output status: pending_confirm -> adopted')
                print(f'  [OK] action_logs: {len(all_logs)} events recorded')
                print('='*50)

        finally:
            app.dependency_overrides.clear()

    finally:
        await db.close()
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(manual_integration_test())
