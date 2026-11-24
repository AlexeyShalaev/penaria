import {
  Cpu,
  DoorOpen,
  House,
  Layers,
  Lock,
  type LucideIcon,
  MapPinHouse,
  Network,
  Package,
  Tag,
  Users,
} from 'lucide-react'

import type {Schemas} from '@/shared/api'

export type Kind = Schemas['Kind']
export type Status = Schemas['Status']
export type Privacy = Schemas['Privacy']
export type ArchiveReason = Schemas['ArchiveReason']
export type Place = Schemas['PlaceOut']

const KINDS: readonly Kind[] = ['property', 'building', 'floor', 'space', 'container', 'item', 'device', 'system']
export const STATUSES: readonly Status[] = ['present', 'missing', 'lent', 'in_repair']
export const PRIVACIES: readonly Privacy[] = ['normal', 'guest_visible', 'private']
export const ARCHIVE_REASONS: readonly ArchiveReason[] = ['discarded', 'sold', 'given_away', 'used_up', 'merged']

// The containment rules of docs/design/core-model.md (section 4.1), as the server enforces them in
// features/core/registry/domain/kinds.py; here they only decide what the forms offer. null is the
// top of the home.
const ALLOWED_PARENTS: Record<Kind, readonly (Kind | null)[]> = {
  property: [null],
  building: ['property'],
  floor: ['building'],
  space: ['property', 'building', 'floor', 'space'],
  container: ['space', 'container', 'item'],
  item: ['space', 'container', 'item'],
  device: ['space', 'container', 'item'],
  system: ['property', 'building', 'system'],
}

/** The kinds that may be added inside a parent of this kind, or at the top of the home for null. */
export function childKinds(parent: Kind | null): Kind[] {
  return KINDS.filter((kind) => ALLOWED_PARENTS[kind].includes(parent))
}

export function canSitIn(kind: Kind, parent: Kind | null): boolean {
  return ALLOWED_PARENTS[kind].includes(parent)
}

export const KIND_ICON: Record<Kind, LucideIcon> = {
  property: MapPinHouse,
  building: House,
  floor: Layers,
  space: DoorOpen,
  container: Package,
  item: Tag,
  device: Cpu,
  system: Network,
}

/** Places that structure the home rather than hold things; the tree shows their names in bold. */
export const STRUCTURAL_KINDS: ReadonlySet<Kind> = new Set(['property', 'building', 'floor'])

/** The mark of a place that not everyone sees the same way; none for normal privacy. */
export const PRIVACY_ICON: Record<Privacy, LucideIcon | null> = {
  normal: null,
  guest_visible: Users,
  private: Lock,
}
