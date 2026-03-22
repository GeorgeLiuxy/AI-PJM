"""Output service - Mock implementation for document generation"""

from typing import Any, Optional


class MockOutputService:
    """Mock output generation service - returns fixed structured content"""

    # output_type to adopted_target mapping
    OUTPUT_TYPE_TO_ADOPTED_TARGET = {
        "prd": "formal_prd",
        "test_points": "test_task",
        "handling_advice": "implementation_note",
    }

    async def generate(
        self,
        output_type: str,
        item_raw_input: str,
        item_final_title: Optional[str],
        analysis_result: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """
        Generate Output (Mock)

        Args:
            output_type: Output type
            item_raw_input: Raw input from Item
            item_final_title: Final title of Item
            analysis_result: Analysis result (optional)

        Returns:
            Fixed structure output
        """
        title = item_final_title or item_raw_input[:50]

        if output_type == "prd":
            return {
                "title": f"{title} PRD",
                "content": f"""# Product Requirements Document

## Background
{item_raw_input}

## Feature Description
Customers want approval nodes to support CC (carbon copy) functionality.

## Scope
1. Approval nodes can add CC users
2. CC users can view progress but no approval required
3. Notification content distinguishes approvers and CC users

## Non-Functional Requirements
- Performance: delay < 100ms when CC users <= 50
- Security: CC users can view but not operate
- Compatibility: compatible with existing approval engine

## Acceptance Criteria
- [ ] Can add CC users when initiating approval
- [ ] CC users receive notification but no approval required
- [ ] Approval progress page shows CC user list
""",
                "summary": f"This document describes the product requirements for {title[:30]}, including feature description, scope, non-functional requirements and acceptance criteria."
            }

        elif output_type == "test_points":
            return {
                "title": f"{title} Test Points",
                "content": f"""# Test Points

## Functional Tests

### 1. Add CC User Test
- Test Point: Approval node can add multiple CC users
- Prerequisite: Approval flow created
- Steps:
  1. Enter approval config page
  2. Select CC personnel
  3. Save config
- Expected: CC users added successfully

### 2. Notification Content Test
- Test Point: Notification content distinguishes approvers and CC users
- Prerequisite: CC users configured
- Steps:
  1. Initiate approval
  2. Check approver notification
  3. Check CC user notification
- Expected: Notification content correctly distinguished

### 3. Permission Test
- Test Point: CC users can only view, not operate
- Prerequisite: Approval initiated
- Steps:
  1. CC user login
  2. Try to click approve button
- Expected: No approve button or permission denied

## Performance Tests
- Notification delay < 100ms when CC users = 50
- 100 concurrent approvals without lag

## Compatibility Tests
- Compatible with existing approval flow
- No impact on existing approval functionality
""",
                "summary": f"This document lists the functional, performance and compatibility test points for {title[:30]}."
            }

        elif output_type == "handling_advice":
            return {
                "title": f"{title} Handling Advice",
                "content": f"""# Handling Advice

## Requirement Analysis
{item_raw_input}

## Implementation Suggestions

### Technical Approach
1. **Data Model**
   - approval_node table add cc_users field
   - Use JSONB to store CC user list

2. **Business Logic**
   - Approval engine add CC logic
   - Notification service distinguishes approvers and CC users

3. **API Design**
   - POST /api/v1/approval-nodes/{{id}}/add-cc
   - GET /api/v1/approval-nodes/{{id}}/cc-list

### Implementation Steps
1. Phase 1 (1 week)
   - Data model adjustment
   - Basic CC functionality development

2. Phase 2 (1 week)
   - Notification logic optimization
   - Frontend page development

3. Phase 3 (3 days)
   - Testing and fixes
   - Deployment

### Risk Warnings
- Old data compatibility needs handling
- Notification service pressure may increase
- Need to inform users about CC feature launch

### Future Optimizations
- CC user permission subdivision (read-only/comment)
- Dynamic add/remove CC users
- CC record query
""",
                "summary": f"This document provides the technical implementation approach, implementation steps, risk warnings and future optimizations for {title[:30]}."
            }

        else:
            raise ValueError(f"Unsupported output_type: {output_type}")

    def get_valid_adopted_target(self, output_type: str) -> str:
        """Get valid adopted_target for given output_type"""
        if output_type not in self.OUTPUT_TYPE_TO_ADOPTED_TARGET:
            raise ValueError(f"Unknown output_type: {output_type}")
        return self.OUTPUT_TYPE_TO_ADOPTED_TARGET[output_type]


# Global service instance
output_service = MockOutputService()
