## 19.0.1.1.0 (2026-08-13)

### Added

- **Delegated attribute management for PIM Manager.** PIM Managers can now
  create and edit attribute sets, groups, attributes and option values without
  the *Settings* (Administration) access. `attribute.attribute` `_inherits`
  `ir.model.fields`, whose write is gated to `base.group_system`, so an ACL
  grant alone left PIM Managers with *"not allowed to access 'Fields'
  (ir.model.fields)"*. The create/write of a custom attribute now verifies the
  user's own `attribute.attribute` right and then elevates only the backing
  field write. Deleting an attribute (dropping the DB column) stays
  Settings-only.

## 19.0.1.0.1 (2026-08-11)

### Added

- `ir.model.access.csv` granting PIM Manager management of attribute option
  values.
