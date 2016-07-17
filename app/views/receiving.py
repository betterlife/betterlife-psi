# coding=utf-8
from datetime import datetime
from functools import partial

from app.service import Info
from flask_admin.contrib.sqla.filters import FloatEqualFilter, FloatSmallerFilter
from flask_admin.contrib.sqla.filters import FloatGreaterFilter
from flask_admin.model import InlineFormAdmin
from app import const
from flask_babelex import lazy_gettext, gettext
from app.views import ModelViewWithAccess
from app.views.components import DisabledStringField
from app.views.base import DeleteValidator
from wtforms import BooleanField
from wtforms.validators import ValidationError

db = Info.get_db()


class ReceivingLineInlineAdmin(InlineFormAdmin):
    form_args = dict(
        purchase_order_line=dict(label=lazy_gettext('Purchase Order Line')),
        quantity=dict(label=lazy_gettext('Quantity')),
        total_amount=dict(label=lazy_gettext('Total Amount')),
    )

    def postprocess_form(self, form):
        form.remark = None
        form.inventory_transaction_line = None
        form.product = None
        form.transient_price = DisabledStringField(label=lazy_gettext('Receiving Price'),
                                                   description=lazy_gettext('Receiving price is brought from purchase '
                                                                            'order and can not be modified in '
                                                                            'receiving line'))
        form.total_amount = DisabledStringField(label=lazy_gettext('Total Amount'))
        form.transient_product = DisabledStringField(label=lazy_gettext('Product'))
        form.price = None
        return form


class ReceivingAdmin(ModelViewWithAccess, DeleteValidator):
    from formatter import supplier_formatter, purchase_order_formatter, inventory_transaction_formatter, default_date_formatter
    from app.models import ReceivingLine, Receiving, PurchaseOrder

    inline_models = (ReceivingLineInlineAdmin(ReceivingLine),)
    column_list = ('id', 'purchase_order', 'supplier', 'date', 'status', 'total_amount', 'inventory_transaction',
                   'remark')
    form_excluded_columns = ('inventory_transaction',)
    form_columns = ('purchase_order', 'transient_po', 'status', 'date',
                    'total_amount', 'remark', 'lines', 'create_lines')
    form_edit_rules = ('transient_po', 'status', 'date', 'total_amount', 'remark', 'lines',)
    column_editable_list = ('remark',)
    form_create_rules = ('purchase_order', 'status', 'date', 'remark', 'create_lines',)
    form_extra_fields = {
        'create_lines': BooleanField(label=lazy_gettext('Create Lines for unreceived products'),
                                     description=lazy_gettext('Create receiving lines based on '
                                                              'not yet received products in the purchase order')),
        'transient_po': DisabledStringField(label=lazy_gettext('Related Purchase Order')),
        "total_amount": DisabledStringField(label=lazy_gettext('Total Amount')),
    }

    column_details_list = ('id', 'supplier', 'date', 'status', 'total_amount', 'remark', 'lines',
                           'purchase_order', 'inventory_transaction',)
    form_widget_args = {
        'create_lines': {'default': True},
    }
    column_sortable_list = ('id', ('supplier', 'id'), ('purchase_order', 'id'), ('status', 'status.display'), 'date',
                            'total_amount')

    column_filters = ('date', 'status.display', 'purchase_order.supplier.name',
                      FloatSmallerFilter(Receiving.total_amount, lazy_gettext('Total Amount')),
                      FloatGreaterFilter(Receiving.total_amount, lazy_gettext('Total Amount')),
                      FloatEqualFilter(Receiving.total_amount, lazy_gettext('Total Amount')))

    column_searchable_list = ('status.display', 'purchase_order.supplier.name', 'remark')
    column_labels = {
        'id': lazy_gettext('id'),
        'purchase_order': lazy_gettext('Related Purchase Order'),
        'supplier': lazy_gettext('Supplier'),
        'status': lazy_gettext('Status'),
        'date': lazy_gettext('Date'),
        'remark': lazy_gettext('Remark'),
        'total_amount': lazy_gettext('Total Amount'),
        'inventory_transaction': lazy_gettext('Inventory Transaction'),
        'lines': lazy_gettext('Lines'),
        'status.display': lazy_gettext('Status'),
        'purchase_order.supplier.name': lazy_gettext('Supplier Name')
    }
    form_args = dict(
        status=dict(query_factory=Receiving.status_filter,
                    description=lazy_gettext('Current status of the receiving document, '
                                             'completed receiving can not be updated or deleted')),
        purchase_order=dict(description=lazy_gettext(
            'Please select a purchase order and save the form, then add receiving lines accordingly'),
            query_factory=partial(PurchaseOrder.status_filter,
                                  (const.PO_ISSUED_STATUS_KEY, const.PO_PART_RECEIVED_STATUS_KEY,))),
        date=dict(default=datetime.now()),
    )

    column_formatters = {
        'supplier': supplier_formatter,
        'purchase_order': purchase_order_formatter,
        'inventory_transaction': inventory_transaction_formatter,
        'date': default_date_formatter,
    }

    def on_model_delete(self, model):
        DeleteValidator.validate_status_for_change(model, const.RECEIVING_COMPLETE_STATUS_KEY,
                                                   gettext('Receiving document can not be update '
                                                           'nor delete on complete status'))

    def on_model_change(self, form, model, is_created):
        from app.models import PurchaseOrder
        super(ReceivingAdmin, self).on_model_change(form, model, is_created)
        if is_created:
            available_info = model.purchase_order.get_available_lines_info()
            # 4. Check any qty available for receiving?
            if PurchaseOrder.all_lines_received(available_info):
                raise ValidationError(gettext('There\'s no unreceived items in this PO.'))
            # 5. Create receiving lines based on the calculated result.
            if model.create_lines:
                model.lines = PurchaseOrder.create_receiving_lines(available_info)
        model.operate_inv_trans_by_recv_status(model)
        model.update_purchase_order_status()
        db.session.commit()

    def create_form(self, obj=None):
        from app.models import EnumValues
        form = super(ReceivingAdmin, self).create_form(obj)
        form.status.query = [EnumValues.find_one_by_code(const.RECEIVING_DRAFT_STATUS_KEY), ]
        form.create_lines.data = True
        return form

    def edit_form(self, obj=None):
        from app.models import PurchaseOrderLine, EnumValues
        form = super(ReceivingAdmin, self).edit_form(obj)
        po_id = obj.transient_po.id
        # Set query_factory for newly added line
        form.lines.form.purchase_order_line.kwargs['query_factory'] = partial(PurchaseOrderLine.header_filter, po_id)
        if obj is not None and obj.status is not None and obj.status.code == const.RECEIVING_COMPLETE_STATUS_KEY:
            form.status.query = [EnumValues.find_one_by_code(const.RECEIVING_COMPLETE_STATUS_KEY), ]
        # Set query option for old lines
        line_entries = form.lines.entries
        po_lines = PurchaseOrderLine.header_filter(po_id).all()
        for sub_line in line_entries:
            sub_line.form.purchase_order_line.query = po_lines
        return form
