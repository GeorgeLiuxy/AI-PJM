import type { AuthUser } from '../types';

export type Capability = 'read' | 'operate' | 'review' | 'admin';

const readRoles = new Set(['admin', 'operator', 'reviewer', 'viewer', 'owner']);
const operateRoles = new Set(['admin', 'operator', 'owner']);
const reviewRoles = new Set(['admin', 'reviewer', 'owner']);
const adminRoles = new Set(['admin', 'owner']);

export function canRead(user: AuthUser | null, projectId?: number | null) {
  return can(user, 'read', projectId);
}

export function canOperate(user: AuthUser | null, projectId?: number | null) {
  return can(user, 'operate', projectId);
}

export function canReview(user: AuthUser | null, projectId?: number | null) {
  return can(user, 'review', projectId);
}

export function canAdmin(user: AuthUser | null, projectId?: number | null) {
  return can(user, 'admin', projectId);
}

export function can(user: AuthUser | null, capability: Capability, projectId?: number | null) {
  if (!user) {
    return false;
  }
  if (!user.auth_enabled) {
    return true;
  }

  const roles = resolveRoles(user, projectId);
  if (capability === 'read') {
    return overlaps(roles, readRoles);
  }
  if (capability === 'operate') {
    return overlaps(roles, operateRoles);
  }
  if (capability === 'review') {
    return overlaps(roles, reviewRoles);
  }
  return overlaps(roles, adminRoles);
}

function resolveRoles(user: AuthUser, projectId?: number | null) {
  if (user.role === 'admin') {
    return new Set(['admin']);
  }
  if (projectId !== undefined && projectId !== null) {
    const projectRole = user.projects.find((project) => project.id === projectId)?.role;
    return projectRole ? new Set([projectRole]) : new Set<string>();
  }
  return new Set([user.role]);
}

function overlaps(left: Set<string>, right: Set<string>) {
  for (const item of left) {
    if (right.has(item)) {
      return true;
    }
  }
  return false;
}
