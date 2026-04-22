from .models import UserPageVisit


class TrackPageVisitMiddleware:
    TRACKED = {
        "/": "Dashboard",
        "/inventory/": "Inventory",
        "/inventory/new/": "Add Product",
        "/inventory/restock/": "Restock",
        "/sales/pos/": "POS Checkout",
        "/sales/report/": "Sales Report",
        "/profile/": "My Profile",
        "/settings/": "Settings",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method == "GET" and request.user.is_authenticated:
            label = self.TRACKED.get(request.path)
            if label:
                visit, _ = UserPageVisit.objects.get_or_create(
                    user=request.user,
                    path=request.path,
                    defaults={"label": label, "count": 0},
                )
                visit.count += 1
                visit.save(update_fields=["count", "last_visited"])
        return response
