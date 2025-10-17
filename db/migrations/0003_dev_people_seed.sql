do $$
declare
    tenant_uuid constant uuid := '11111111-1111-1111-1111-111111111111';
    staff_target int := 100;
    member_target int := 100;
    staff_remaining int;
    member_remaining int;
    staff_count int := 0;
    member_count int := 0;
    household_id uuid;
    entity_id uuid;
    first_name text;
    last_name text;
    email text;
    phone text;
    phone_suffix int;
    age_years int;
    gender text;
    role_in_household text;
    members_in_house int;
    volunteer bool;
    volunteer_roles text[];
    tags_array text[];
    status_label text;
    job_title text;
    department text;
    first_names text[] := array[
        'Avery','Benjamin','Charlotte','Daniel','Evelyn','Finn','Grace','Harper','Isaac','Julia',
        'Kai','Liam','Maya','Noah','Olivia','Parker','Quinn','Riley','Sophia','Theo',
        'Uma','Violet','Willow','Xavier','Yara','Zane','Amelia','Beckett','Clara','Dylan',
        'Elijah','Fiona','Graham','Hazel','Ian','Jasper','Kendall','Logan','Mila','Nora',
        'Owen','Penelope','Rowan','Stella','Tristan','Valerie','Wyatt','Zoey','Henry','Isla'
    ];
    last_names text[] := array[
        'Anderson','Bennett','Carter','Diaz','Ellis','Fletcher','Garcia','Hayes','Ingram','Johnson',
        'Kim','Lopez','Mitchell','Nguyen','Owens','Patel','Quinn','Robinson','Stewart','Turner',
        'Underwood','Vargas','White','Xiong','Young','Zimmerman','Baker','Coleman','Dawson','Evans',
        'Fisher','Gonzalez','Harris','Irwin','Jackson','Keller','Lam','Morgan','Nash','Ortega',
        'Perry','Reed','Sanders','Taylor','Usher','Vaughn','Walker','Xu','York','Zhang'
    ];
    staff_roles text[] := array[
        'Lead Pastor','Teaching Pastor','Executive Pastor','Youth Director','Kids Director',
        'Worship Pastor','Creative Director','Discipleship Pastor','Outreach Coordinator','Prayer Pastor',
        'Hospitality Lead','Facilities Manager','Operations Director','Next Steps Pastor','Production Lead'
    ];
    staff_departments text[] := array[
        'Leadership','Teaching','Operations','Youth','Kids','Worship','Creative','Groups','Outreach','Prayer',
        'Hospitality','Facilities','Production','Pastoral Care','Missions'
    ];
    member_statuses text[] := array[
        'Active Volunteer','Core Volunteer','Occasional Volunteer','Member','New Attender','Guest'
    ];
    member_ministries text[] := array[
        'Kids Ministry','Youth','Greeting Team','Prayer Team','Production','Worship','Cafe','Parking','Community Groups','Hospitality'
    ];
    volunteer_role1 text;
    volunteer_role2 text;
begin
    select staff_target - count(*) into staff_remaining
    from person
    where tenant_id = tenant_uuid
      and contact_json ->> 'seed_tag' = 'dev_seed_staff';

    if staff_remaining < 0 then
        staff_remaining := 0;
    end if;

    while staff_count < staff_remaining loop
        household_id := gen_random_uuid();
        insert into household (id, tenant_id, name, address_json, created_at, updated_at, deleted_at)
        values (
            household_id,
            tenant_uuid,
            format('Staff Household %s', staff_count + 1),
            jsonb_build_object(
                'street', format('%s Shepherd Way', 500 + staff_count),
                'city', 'Springfield',
                'state', 'IL',
                'zip', to_char(62700 + staff_count, 'FM00000')
            ),
            now(),
            now(),
            null
        );

        members_in_house := least(staff_remaining - staff_count, 1 + floor(random() * 3)::int);

        for i in 1..members_in_house loop
            staff_count := staff_count + 1;

            first_name := first_names[1 + floor(random() * array_length(first_names, 1))::int];
            last_name := last_names[1 + floor(random() * array_length(last_names, 1))::int];
            job_title := staff_roles[1 + floor(random() * array_length(staff_roles, 1))::int];
            department := staff_departments[1 + floor(random() * array_length(staff_departments, 1))::int];
            email := lower(first_name || '.' || last_name || staff_count || '@churchbrain.test');
            phone_suffix := 1000 + floor(random() * 9000)::int;
            phone := '(555) ' || to_char(200 + staff_count, 'FM000') || '-' || to_char(phone_suffix, 'FM0000');
            age_years := 28 + floor(random() * 20)::int;
            gender := case when random() < 0.5 then 'F' else 'M' end;
            role_in_household := case
                when i = 1 then 'Head'
                when i = 2 then 'Spouse'
                else 'Dependent'
            end;
            tags_array := array['staff', department, job_title, 'dev_seed'];

            entity_id := gen_random_uuid();
            insert into entity (id, tenant_id, type, created_at, updated_at, deleted_at, created_by, updated_by)
            values (entity_id, tenant_uuid, 'staff', now(), now(), null, null, null);

            insert into person (
                entity_id,
                tenant_id,
                first_name,
                last_name,
                dob,
                gender,
                contact_json,
                primary_household_id,
                created_at,
                updated_at,
                deleted_at
            )
            values (
                entity_id,
                tenant_uuid,
                first_name,
                last_name,
                (current_date - make_interval(years => age_years)),
                gender,
                jsonb_build_object(
                    'email', email,
                    'phone', phone,
                    'department', department,
                    'role', job_title,
                    'volunteer', true,
                    'tags', to_jsonb(tags_array),
                    'seed_tag', 'dev_seed_staff'
                ),
                household_id,
                now(),
                now(),
                null
            );

            insert into person_household (
                person_id,
                household_id,
                tenant_id,
                role_in_household,
                is_primary,
                created_at,
                updated_at
            )
            values (
                entity_id,
                household_id,
                tenant_uuid,
                role_in_household,
                (i = 1),
                now(),
                now()
            );

            exit when staff_count >= staff_remaining;
        end loop;
    end loop;

    select member_target - count(*) into member_remaining
    from person
    where tenant_id = tenant_uuid
      and contact_json ->> 'seed_tag' = 'dev_seed_member';

    if member_remaining < 0 then
        member_remaining := 0;
    end if;

    while member_count < member_remaining loop
        household_id := gen_random_uuid();
        insert into household (id, tenant_id, name, address_json, created_at, updated_at, deleted_at)
        values (
            household_id,
            tenant_uuid,
            format('Member Household %s', member_count + 1),
            jsonb_build_object(
                'street', format('%s Grace Ave', 900 + member_count),
                'city', 'Springfield',
                'state', 'IL',
                'zip', to_char(62750 + member_count, 'FM00000')
            ),
            now(),
            now(),
            null
        );

        members_in_house := least(member_remaining - member_count, 2 + floor(random() * 3)::int);

        for j in 1..members_in_house loop
            member_count := member_count + 1;

            first_name := first_names[1 + floor(random() * array_length(first_names, 1))::int];
            last_name := last_names[1 + floor(random() * array_length(last_names, 1))::int];
            volunteer := random() < 0.65;
            volunteer_role1 := member_ministries[1 + floor(random() * array_length(member_ministries, 1))::int];
            volunteer_role2 := member_ministries[1 + floor(random() * array_length(member_ministries, 1))::int];
            volunteer_roles := case
                when volunteer then array[volunteer_role1, volunteer_role2]
                else array[]::text[]
            end;
            status_label := member_statuses[1 + floor(random() * array_length(member_statuses, 1))::int];
            email := lower(first_name || '.' || last_name || member_count || '@attender.test');
            phone_suffix := 2000 + floor(random() * 8000)::int;
            phone := '(312) ' || to_char(400 + member_count, 'FM000') || '-' || to_char(phone_suffix, 'FM0000');
            gender := case when random() < 0.5 then 'F' else 'M' end;
            if j <= 2 then
                age_years := 26 + floor(random() * 25)::int;
            else
                age_years := 6 + floor(random() * 25)::int;
            end if;
            role_in_household := case
                when j = 1 then 'Head'
                when j = 2 then 'Spouse'
                else 'Dependent'
            end;
            tags_array := array['member', 'dev_seed'] ||
                case when volunteer then array['volunteer'] else array[]::text[] end;

            entity_id := gen_random_uuid();
            insert into entity (id, tenant_id, type, created_at, updated_at, deleted_at, created_by, updated_by)
            values (entity_id, tenant_uuid, 'member', now(), now(), null, null, null);

            insert into person (
                entity_id,
                tenant_id,
                first_name,
                last_name,
                dob,
                gender,
                contact_json,
                primary_household_id,
                created_at,
                updated_at,
                deleted_at
            )
            values (
                entity_id,
                tenant_uuid,
                first_name,
                last_name,
                (current_date - make_interval(years => age_years)),
                gender,
                jsonb_build_object(
                    'email', email,
                    'phone', phone,
                    'volunteer', volunteer,
                    'volunteer_roles', to_jsonb(volunteer_roles),
                    'status', status_label,
                    'tags', to_jsonb(tags_array),
                    'seed_tag', 'dev_seed_member'
                ),
                household_id,
                now(),
                now(),
                null
            );

            insert into person_household (
                person_id,
                household_id,
                tenant_id,
                role_in_household,
                is_primary,
                created_at,
                updated_at
            )
            values (
                entity_id,
                household_id,
                tenant_uuid,
                role_in_household,
                (j = 1),
                now(),
                now()
            );

            exit when member_count >= member_remaining;
        end loop;
    end loop;
end
$$;
