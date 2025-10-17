-- Dev convenience seed so local testing has known UUIDs
insert into tenant (id, name)
values ('11111111-1111-1111-1111-111111111111', 'Demo Tenant')
on conflict (id) do nothing;

insert into entity (id, tenant_id, type)
values ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'person')
on conflict (id) do nothing;
