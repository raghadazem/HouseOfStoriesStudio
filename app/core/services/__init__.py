"""Application service layer: the domain models made usable.

Every service is a small, stateless-ish class whose methods take an
already-open SQLAlchemy :class:`~sqlalchemy.orm.Session` as their first
argument (after ``self``) — see ``app/core/services/unit_of_work.py``
for how transaction boundaries are managed. Services contain business
logic; models stay thin data holders (see ``app/core/models/``); no
service imports anything from ``app/gui/``.
"""
