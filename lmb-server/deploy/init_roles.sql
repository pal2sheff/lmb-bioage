-- Выполняется суперпользователем один раз при развёртывании.
-- lmb_admin: владелец схемы, миграции и начальная настройка; обходит RLS.
-- lmb_app: роль приложения; не обходит RLS; журнал аудита — только добавление.
-- Пароли задаются при развёртывании и хранятся в хранилище секретов.
CREATE ROLE lmb_admin LOGIN BYPASSRLS PASSWORD :'admin_password';
CREATE ROLE lmb_app LOGIN NOBYPASSRLS PASSWORD :'app_password';
CREATE DATABASE lmb OWNER lmb_admin;
