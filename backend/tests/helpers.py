def cls(name: str, methods=1, fields=0, abstract=False, interface=False, annotations=None):
    return dict(fqn=name,simple_name=name.rsplit('.',1)[-1],package_name=name.rpartition('.')[0],
        method_count=methods,field_count=fields,is_abstract=abstract,is_interface=interface,annotations=annotations or [])

def edge(source,target,kind='METHOD_CALL'):
    return dict(source=source,target=target,dependency_type=kind)

def sample():
    classes=[cls('com.shop.payment.PaymentService'),cls('com.shop.payment.PaymentEntity',annotations=['jakarta.persistence.Entity']),
        cls('com.shop.orders.OrderService'),cls('com.shop.notification.NotificationService'),cls('com.shop.notification.Template')]
    edges=[edge('com.shop.payment.PaymentService','com.shop.orders.OrderService'),
        edge('com.shop.orders.OrderService','com.shop.payment.PaymentService'),
        edge('com.shop.payment.PaymentService','com.shop.payment.PaymentEntity'),
        edge('com.shop.notification.NotificationService','com.shop.notification.Template'),
        edge('com.shop.payment.PaymentService','java.sql.Connection','FIELD_TYPE')]
    return classes,edges
