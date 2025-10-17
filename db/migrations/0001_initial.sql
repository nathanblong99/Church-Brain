-- Enable UUID generation helpers
create extension if not exists "pgcrypto";

-- Tenancy root
create table tenant (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_at timestamptz not null default now()
);

-- Core entity backbone
create table entity (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    type text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    created_by uuid references entity(id),
    updated_by uuid references entity(id)
);

create table household (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    name text not null,
    address_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create table person (
    entity_id uuid primary key references entity(id) on delete cascade,
    tenant_id uuid not null references tenant(id),
    first_name text not null,
    last_name text not null,
    dob date,
    gender text,
    contact_json jsonb,
    primary_household_id uuid references household(id),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create table person_household (
    person_id uuid not null references person(entity_id) on delete cascade,
    household_id uuid not null references household(id) on delete cascade,
    tenant_id uuid not null references tenant(id),
    role_in_household text not null,
    is_primary boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (person_id, household_id)
);

-- Workflow backbone
create table request (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    request_type text not null,
    status text not null,
    requested_by_entity_id uuid references entity(id),
    subject_entity_id uuid references entity(id),
    priority text,
    due_at timestamptz,
    shard_key text,
    payload_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create table assignment (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    request_id uuid not null references request(id) on delete cascade,
    assignee_entity_id uuid references entity(id),
    status text not null,
    assigned_at timestamptz not null default now(),
    due_at timestamptz,
    notes text,
    metadata_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create table resource_link (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    owner_type text not null,
    owner_id uuid not null,
    resource_type text not null,
    resource_id uuid not null,
    role text,
    attributes_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint resource_link_owner_type_chk check (owner_type in ('request', 'assignment'))
);

-- Conversations & Messaging
create table conversation (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    request_id uuid references request(id) on delete set null,
    topic text,
    started_by_entity_id uuid references entity(id),
    channel text not null,
    state text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz
);

create table message_log (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references conversation(id) on delete cascade,
    tenant_id uuid not null references tenant(id),
    from_entity_id uuid references entity(id),
    to_entity_id uuid references entity(id),
    direction text not null,
    channel text not null,
    body text,
    status text,
    provider_ids_json jsonb,
    sent_at timestamptz,
    received_at timestamptz,
    metadata_json jsonb,
    created_at timestamptz not null default now()
);

create table communication_pref (
    entity_id uuid not null references entity(id) on delete cascade,
    tenant_id uuid not null references tenant(id),
    channel text not null,
    is_opted_in boolean not null default false,
    window_json jsonb,
    last_opt_event_at timestamptz,
    updated_at timestamptz not null default now(),
    primary key (entity_id, channel)
);

-- Catalog & Customization
create table catalog_item (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    domain text not null,
    code text not null,
    label text not null,
    sort integer,
    active boolean not null default true,
    metadata_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    deleted_at timestamptz,
    constraint catalog_item_domain_code_uniq unique (tenant_id, domain, code)
);

create table custom_field_def (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    entity_type text not null,
    field_name text not null,
    field_kind text not null,
    validation_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint custom_field_def_name_uniq unique (tenant_id, entity_type, field_name)
);

create table custom_field_val (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    entity_type text not null,
    entity_id uuid not null,
    field_id uuid not null references custom_field_def(id) on delete cascade,
    value_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint custom_field_val_entity_field_uniq unique (tenant_id, entity_type, entity_id, field_id)
);

-- Auth / Security
create table user_account (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    entity_id uuid references entity(id),
    email text not null,
    password_hash text,
    mfa_json jsonb,
    is_active boolean not null default true,
    last_login_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint user_account_tenant_email_uniq unique (tenant_id, email)
);

create table role (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    code text not null,
    label text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint role_tenant_code_uniq unique (tenant_id, code)
);

create table permission (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    code text not null,
    label text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint permission_tenant_code_uniq unique (tenant_id, code)
);

create table user_role (
    user_id uuid not null references user_account(id) on delete cascade,
    role_id uuid not null references role(id) on delete cascade,
    assigned_at timestamptz not null default now(),
    primary key (user_id, role_id)
);

create table role_permission (
    role_id uuid not null references role(id) on delete cascade,
    permission_id uuid not null references permission(id) on delete cascade,
    granted_at timestamptz not null default now(),
    primary key (role_id, permission_id)
);

-- Audit
create table audit_log (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    table_name text not null,
    row_pk text not null,
    action text not null,
    changed_by uuid references entity(id),
    changed_at timestamptz not null default now(),
    diff_json jsonb
);

-- Helpful indexes
create index idx_entity_tenant_type on entity (tenant_id, type);
create index idx_person_tenant_name on person (tenant_id, last_name, first_name);
create index idx_request_tenant_status on request (tenant_id, status);
create index idx_assignment_tenant_status on assignment (tenant_id, status);
create index idx_message_log_tenant_channel on message_log (tenant_id, channel);
create index idx_custom_field_val_entity on custom_field_val (tenant_id, entity_type, entity_id);
