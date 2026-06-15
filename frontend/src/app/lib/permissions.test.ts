/**
 * Tests for permissions.ts
 */

import { describe, it, expect } from 'vitest'
import { can, canRead, canOperate, canReview, canAdmin, type Capability } from './permissions'
import type { AuthUser } from '../types'

describe('permissions.ts - Capability Types', () => {
  it('should have valid capability types', () => {
    const capabilities: Capability[] = ['read', 'operate', 'review', 'admin']
    expect(capabilities).toHaveLength(4)
  })
})

describe('permissions.ts - can function', () => {
  const createMockUser = (overrides?: Partial<AuthUser>): AuthUser => ({
    id: 1,
    username: 'testuser',
    role: 'viewer',
    auth_enabled: true,
    projects: [],
    ...overrides
  })

  it('should return false for null user', () => {
    expect(can(null, 'read')).toBe(false)
    expect(can(null, 'operate')).toBe(false)
    expect(can(null, 'review')).toBe(false)
    expect(can(null, 'admin')).toBe(false)
  })

  it('should return true when auth is disabled', () => {
    const user = createMockUser({ auth_enabled: false })
    expect(can(user, 'read')).toBe(true)
    expect(can(user, 'operate')).toBe(true)
    expect(can(user, 'review')).toBe(true)
    expect(can(user, 'admin')).toBe(true)
  })

  it('should handle admin global role correctly', () => {
    const adminUser = createMockUser({ role: 'admin' })
    expect(can(adminUser, 'read')).toBe(true)
    expect(can(adminUser, 'operate')).toBe(true)
    expect(can(adminUser, 'review')).toBe(true)
    expect(can(adminUser, 'admin')).toBe(true)
  })

  it('should handle owner global role correctly', () => {
    const ownerUser = createMockUser({ role: 'owner' })
    expect(can(ownerUser, 'read')).toBe(true)
    expect(can(ownerUser, 'operate')).toBe(true)
    expect(can(ownerUser, 'review')).toBe(true)
    expect(can(ownerUser, 'admin')).toBe(true)
  })

  it('should handle operator global role correctly', () => {
    const operatorUser = createMockUser({ role: 'operator' })
    expect(can(operatorUser, 'read')).toBe(true)
    expect(can(operatorUser, 'operate')).toBe(true)
    expect(can(operatorUser, 'review')).toBe(false)
    expect(can(operatorUser, 'admin')).toBe(false)
  })

  it('should handle reviewer global role correctly', () => {
    const reviewerUser = createMockUser({ role: 'reviewer' })
    expect(can(reviewerUser, 'read')).toBe(true)
    expect(can(reviewerUser, 'operate')).toBe(false)
    expect(can(reviewerUser, 'review')).toBe(true)
    expect(can(reviewerUser, 'admin')).toBe(false)
  })

  it('should handle viewer global role correctly', () => {
    const viewerUser = createMockUser({ role: 'viewer' })
    expect(can(viewerUser, 'read')).toBe(true)
    expect(can(viewerUser, 'operate')).toBe(false)
    expect(can(viewerUser, 'review')).toBe(false)
    expect(can(viewerUser, 'admin')).toBe(false)
  })

  it('should handle project-specific permissions correctly', () => {
    const user = createMockUser({
      role: 'viewer',
      projects: [
        { id: 1, key: 'PROJ1', name: 'Project 1', role: 'operator' },
        { id: 2, key: 'PROJ2', name: 'Project 2', role: 'admin' }
      ]
    })

    // Project 1 - operator role
    expect(can(user, 'read', 1)).toBe(true)
    expect(can(user, 'operate', 1)).toBe(true)
    expect(can(user, 'review', 1)).toBe(false)
    expect(can(user, 'admin', 1)).toBe(false)

    // Project 2 - admin role
    expect(can(user, 'read', 2)).toBe(true)
    expect(can(user, 'operate', 2)).toBe(true)
    expect(can(user, 'review', 2)).toBe(true)
    expect(can(user, 'admin', 2)).toBe(true)

    // Non-existent project
    expect(can(user, 'read', 999)).toBe(false)
  })

  it('should use global admin role when user is global admin', () => {
    const user = createMockUser({
      role: 'admin',
      projects: [
        { id: 1, key: 'PROJ1', name: 'Project 1', role: 'viewer' }
      ]
    })

    // Global admin should have all permissions regardless of project role
    expect(can(user, 'read', 1)).toBe(true)
    expect(can(user, 'operate', 1)).toBe(true)
    expect(can(user, 'review', 1)).toBe(true)
    expect(can(user, 'admin', 1)).toBe(true)

    // Without project ID, should also have all permissions
    expect(can(user, 'read')).toBe(true)
    expect(can(user, 'operate')).toBe(true)
    expect(can(user, 'review')).toBe(true)
    expect(can(user, 'admin')).toBe(true)
  })
})

describe('permissions.ts - Helper functions', () => {
  const createMockUser = (overrides?: Partial<AuthUser>): AuthUser => ({
    id: 1,
    username: 'testuser',
    role: 'viewer',
    auth_enabled: true,
    projects: [],
    ...overrides
  })

  it('canRead should check read permission', () => {
    const user = createMockUser({ role: 'viewer' })
    expect(canRead(user)).toBe(true)
  })

  it('canRead should return false for null user', () => {
    expect(canRead(null)).toBe(false)
  })

  it('canOperate should check operate permission', () => {
    const user = createMockUser({ role: 'operator' })
    expect(canOperate(user)).toBe(true)
  })

  it('canOperate should return false for insufficient role', () => {
    const user = createMockUser({ role: 'viewer' })
    expect(canOperate(user)).toBe(false)
  })

  it('canReview should check review permission', () => {
    const user = createMockUser({ role: 'reviewer' })
    expect(canReview(user)).toBe(true)
  })

  it('canReview should return false for insufficient role', () => {
    const user = createMockUser({ role: 'operator' })
    expect(canReview(user)).toBe(false)
  })

  it('canAdmin should check admin permission', () => {
    const user = createMockUser({ role: 'admin' })
    expect(canAdmin(user)).toBe(true)
  })

  it('canAdmin should return false for insufficient role', () => {
    const user = createMockUser({ role: 'operator' })
    expect(canAdmin(user)).toBe(false)
  })

  it('should handle project-specific read permissions', () => {
    const user = createMockUser({
      role: 'viewer',
      projects: [
        { id: 1, key: 'PROJ1', name: 'Project 1', role: 'operator' }
      ]
    })
    expect(canRead(user, 1)).toBe(true)
  })

  it('should handle project-specific operate permissions', () => {
    const user = createMockUser({
      role: 'viewer',
      projects: [
        { id: 1, key: 'PROJ1', name: 'Project 1', role: 'operator' }
      ]
    })
    expect(canOperate(user, 1)).toBe(true)
  })

  it('should handle project-specific review permissions', () => {
    const user = createMockUser({
      role: 'viewer',
      projects: [
        { id: 1, key: 'PROJ1', name: 'Project 1', role: 'reviewer' }
      ]
    })
    expect(canReview(user, 1)).toBe(true)
  })

  it('should handle project-specific admin permissions', () => {
    const user = createMockUser({
      role: 'viewer',
      projects: [
        { id: 1, key: 'PROJ1', name: 'Project 1', role: 'admin' }
      ]
    })
    expect(canAdmin(user, 1)).toBe(true)
  })
})