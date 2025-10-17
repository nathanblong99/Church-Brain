-- Guest pairing persistence tables

create table guest_connection_volunteer (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    name text not null,
    phone text not null,
    age_range text,
    gender text,
    marital_status text,
    active boolean not null default true,
    currently_assigned_request_id uuid,
    last_matched_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table guest_connection_request (
    id uuid primary key default gen_random_uuid(),
    tenant_id uuid not null references tenant(id),
    guest_name text not null,
    contact text not null,
    age_range text,
    gender text,
    marital_status text,
    status text not null default 'OPEN',
    volunteer_id uuid references guest_connection_volunteer(id),
    notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_guest_request_tenant_status on guest_connection_request (tenant_id, status);
create index idx_guest_request_volunteer on guest_connection_request (tenant_id, volunteer_id);
create index idx_guest_volunteer_tenant_active on guest_connection_volunteer (tenant_id, active);
create unique index idx_guest_volunteer_phone on guest_connection_volunteer (tenant_id, phone);
