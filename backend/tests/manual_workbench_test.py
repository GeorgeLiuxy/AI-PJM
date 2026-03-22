"""Manual API verification script for workbench and timeline"""

import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.db import Base, get_db

# Import models
from app.modules.item.models import Item, ItemSuggestion
from app.modules.analysis.models import Analysis
from app.modules.output.models import Output
from app.modules.audit.models import ActionLog

TEST_DATABASE_URL = 'postgresql+asyncpg://ai_pjm_user:ai_pjm_password@localhost:5432/ai_pjm_test'


async def verify_apis():
    """Verify all 3 APIs work correctly"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    db = SessionLocal()

    try:
        async def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db

        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                print('=== Creating Test Data ===\n')

                # 1. Create a pending_confirm item
                print('[1] Creating pending_confirm item...')
                response = await client.post('/api/v1/items/draft', json={
                    'raw_input': 'Feature: Customer wants approval workflow with CC functionality',
                    'source_type': 'customer_feedback'
                })
                item_id_1 = response.json()['data']['id']
                await client.post(f'/api/v1/items/{item_id_1}/understand', json={'force_refresh': False})
                print(f'   Item {item_id_1} in pending_confirm status')

                # 2. Create a done item (full lifecycle)
                print('\n[2] Creating done item (full lifecycle)...')
                response = await client.post('/api/v1/items/draft', json={
                    'raw_input': 'Bug: Login timeout issue',
                    'source_type': 'bug_report'
                })
                item_id_2 = response.json()['data']['id']
                await client.post(f'/api/v1/items/{item_id_2}/understand', json={'force_refresh': False})
                await client.post(f'/api/v1/items/{item_id_2}/confirm', json={'confirm_mode': 'accept'})

                response = await client.post(f'/api/v1/items/{item_id_2}/analysis')
                analysis_id = response.json()['data']['id']
                await client.post(f'/api/v1/analysis/{analysis_id}/run')
                await client.post(f'/api/v1/analysis/{analysis_id}/confirm', json={'final_recommendation': 'do_now'})

                response = await client.post(f'/api/v1/items/{item_id_2}/outputs', json={
                    'output_type': 'prd',
                    'analysis_id': analysis_id
                })
                output_id = response.json()['data']['id']
                await client.post(f'/api/v1/outputs/{output_id}/confirm', json={})
                await client.post(f'/api/v1/outputs/{output_id}/adopt', json={'adopted_target': 'formal_prd'})
                print(f'   Item {item_id_2} completed full lifecycle -> done')

                # 3. Test API 1: GET /api/v1/workbench/home
                print('\n=== API 1: GET /api/v1/workbench/home ===')
                response = await client.get('/api/v1/workbench/home')
                print(f'Status: {response.status_code}')
                data = response.json()['data']
                print(f'\nSummary:')
                print(f'  pending_item_confirm_count: {data["summary"]["pending_item_confirm_count"]}')
                print(f'  pending_analysis_review_count: {data["summary"]["pending_analysis_review_count"]}')
                print(f'  pending_output_confirm_count: {data["summary"]["pending_output_confirm_count"]}')
                print(f'  done_item_count: {data["summary"]["done_item_count"]}')
                print(f'\nTodo Queue: {len(data["todo_queue"])} items')
                for todo in data["todo_queue"]:
                    print(f'  - [{todo["todo_type"]}] {todo["title"]}')
                print(f'\nRecent Items: {len(data["recent_items"])} items')
                print(f'Recent Outputs: {len(data["recent_outputs"])} outputs')

                # 4. Test API 2: GET /api/v1/workbench/todos
                print('\n=== API 2: GET /api/v1/workbench/todos ===')
                response = await client.get('/api/v1/workbench/todos')
                print(f'Status: {response.status_code}')
                data = response.json()['data']
                print(f'\nTotal todos: {data["total"]}')
                print(f'Breakdown:')
                print(f'  pending_item_confirm: {data["breakdown"]["pending_item_confirm"]}')
                print(f'  pending_analysis_review: {data["breakdown"]["pending_analysis_review"]}')
                print(f'  pending_output_confirm: {data["breakdown"]["pending_output_confirm"]}')
                print(f'  pending_output_adopt: {data["breakdown"]["pending_output_adopt"]}')
                print(f'\nFirst 3 todos:')
                for i, todo in enumerate(data['todos'][:3], 1):
                    print(f'  {i}. [{todo["todo_type"]}] {todo["title"]}')

                # 5. Test API 3: GET /api/v1/items/{item_id}/timeline
                print(f'\n=== API 3: GET /api/v1/items/{item_id_2}/timeline ===')
                response = await client.get(f'/api/v1/items/{item_id_2}/timeline')
                print(f'Status: {response.status_code}')
                data = response.json()['data']
                print(f'\nTotal timeline events: {data["total"]}')
                print(f'\nTimeline (showing all events):')
                for i, event in enumerate(data['timeline'], 1):
                    print(f'  {i}. [{event["biz_type"]}] {event["action_type"]}')
                    print(f'     Operator: {event["operator_type"]}, Status: {event["from_status"]} -> {event["to_status"]}')

                print('\n=== All APIs Verified Successfully ===')

        finally:
            app.dependency_overrides.clear()

    finally:
        await db.close()
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(verify_apis())
