from django.utils import timezone
from django.core.cache import cache
from django.db.models import Avg, Sum
from typing import Any
from django.db.models.query import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from .models import (
    CartItem,
    Category,
    Order,
    OrderItem,
    Product,
    Cart,
    АvailabilityAlert,
)
from django.views.generic import (
    ListView,
    DetailView,
    FormView,
    TemplateView,
    UpdateView,
    CreateView,
    DeleteView,
)
from .forms import OrderForm, UserRegistrationForm, PaymentForm
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.models import User
from django.core.mail import send_mail

from .fake_payment_system import FakePaymentSystem
from .payment_gateaway import PaymentSystem


def gmail_mail(request):
    return HttpResponse("Вы отправили email")


class ManagerMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.groups.filter(name="Менеджеры").exists()


class ManagerDashboardView(ManagerMixin, TemplateView):
    template_name = "manager/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["users_count"] = cache.get("users_count")
        if context["users_count"] is None:
            context["users_count"] = User.objects.count()
            cache.set("users_count", context["users_count"], timeout=300)

        context["orders_count"] = cache.get("orders_count")
        if context["orders_count"] is None:
            context["orders_count"] = Order.objects.count()
            cache.set("orders_count", context["orders_count"], timeout=300)

        context["completed_orders_count"] = cache.get("completed_orders_count")
        if context["completed_orders_count"] is None:
            context["completed_orders_count"] = Order.objects.filter(
                status="completed"
            ).count()
            cache.set(
                "completed_orders_count", context["completed_orders_count"], timeout=300
            )

        context["new_orders_count"] = cache.get("new_orders_count")
        if context["new_orders_count"] is None:
            context["new_orders_count"] = Order.objects.filter(
                created_at__gte=timezone.now() - timezone.timedelta(days=1)
            ).count()
            cache.set("new_orders_count", context["new_orders_count"], timeout=300)

        context["returned_orders_count"] = cache.get("returned_orders_count")
        if context["returned_orders_count"] is None:
            context["returned_orders_count"] = Order.objects.filter(
                status="returned"
            ).count()
            cache.set(
                "returned_orders_count", context["returned_orders_count"], timeout=300
            )

        context["total_revenue"] = cache.get("total_revenue")
        if context["total_revenue"] is None:
            context["total_revenue"] = Order.objects.get_revenue()
            cache.set("total_revenue", context["total_revenue"], timeout=300)

        context["average_order_value"] = cache.get("average_order_value")
        if context["average_order_value"] is None:
            context["average_order_value"] = Order.objects.aggregate(
                avg_value=Avg("total_price")
            )["avg_value"]
            cache.set(
                "average_order_value", context["average_order_value"], timeout=300
            )

        context["top_customers"] = cache.get("top_customers")
        if context["top_customers"] is None:
            context["top_customers"] = User.objects.annotate(
                total_spent=Sum("orders__total_price")
            ).order_by("-total_spent")[:5]
            cache.set("top_customers", context["top_customers"], timeout=300)

        context["total_sold"] = cache.get("total_sold")
        if context["total_sold"] is None:
            context["total_sold"] = OrderItem.objects.get_count_products_sold()
            cache.set("total_sold", context["total_sold"], timeout=300)

        context["active_users_count"] = cache.get("active_users_count")
        if context["active_users_count"] is None:
            context["active_users_count"] = (
                User.objects.filter(
                    orders__created_at__gte=timezone.now() - timezone.timedelta(days=30)
                )
                .distinct()
                .count()
            )
            cache.set("active_users_count", context["active_users_count"], timeout=300)

        return context


class ManagerOrdersView(ManagerMixin, ListView):
    model = Order
    template_name = "manager/orders.html"
    context_object_name = "orders"
    ordering = ["-created_at"]
    paginate_by = 10


class ManagerProductsView(ManagerMixin, ListView):
    model = Product
    template_name = "manager/products.html"
    context_object_name = "products"
    ordering = ["-created_at"]
    paginate_by = 10


class ManagerProductsUpdateView(ManagerMixin, UpdateView):
    model = Product
    template_name = "manager/product_update.html"
    context_object_name = "product"
    ordering = ["-created_at"]
    fields = ["description", "price", "discount_price", "category", "image", "quantity"]
    success_url = reverse_lazy("manager_products")


class ManagerProductsDeleteView(ManagerMixin, DeleteView):
    template_name = "manager/product_confirm_delete.html"
    model = Product
    success_url = reverse_lazy("manager_products")


class ManagerProductsAddView(ManagerMixin, CreateView):
    model = Product
    template_name = "manager/product_add.html"
    fields = [
        "name",
        "description",
        "price",
        "discount_price",
        "category",
        "image",
        "quantity",
    ]
    success_url = reverse_lazy("manager_products")

    def form_valid(self, form):
        print("Форма валидна")
        return super().form_valid(form)


class ManagerOrdersUpdateView(ManagerMixin, UpdateView):
    model = Order
    template_name = "manager/orders_update.html"
    fields = ["status", "payment_status", "address"]
    success_url = reverse_lazy("manager_orders")


class CartDetailView(TemplateView, LoginRequiredMixin):
    template_name = "cart/cart_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cart = get_object_or_404(Cart, user=self.request.user)
        context["cart"] = cart
        return context


class AddToCartView(View, LoginRequiredMixin):
    def post(self, request, *args, **kwargs):
        product = get_object_or_404(Product, slug=self.kwargs["slug"])
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)
        if not created:
            if product.quantity > (cart_item.quantity):
                cart_item.quantity += 1
        cart_item.save()
        return redirect("cart")


class RemoveToCartView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        cart = get_object_or_404(Cart, user=self.request.user)
        product = get_object_or_404(Product, slug=self.kwargs["slug"])
        cart_item = get_object_or_404(CartItem, cart=cart, product=product)
        if cart_item.quantity > 1:
            cart_item.quantity -= 1
            cart_item.save()  # Сохраните изменения в базе данных
        else:
            cart_item.delete()
        return redirect("cart")


class CustomLoginView(LoginView):
    template_name = "accounts/login.html"
    success_url = reverse_lazy("product_list")


class CustomLogoutView(LogoutView):
    template_name = "accounts/logout.html"
    success_url = reverse_lazy("product_list")


class SignUp(FormView):
    template_name = "accounts/signup.html"
    form_class = UserRegistrationForm
    success_url = reverse_lazy("product_list")

    def form_valid(self, form):
        user = form.save()
        send_mail(
            "Добро пожаловать в магазин ItStepShop",
            "Держи промокод NEWUSER",
            "olzhas2201@gmail.com",
            [user.email],
            fail_silently=False,
        )
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        return super().form_valid(form)


class ProductListView(ListView):
    model = Product
    template_name = "shop/product/list.html"
    context_object_name = "products"
    ordering = ["-created_at"]
    paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        categoty_slug = self.kwargs.get("category_slug")
        if categoty_slug:
            category = get_object_or_404(Category, slug=categoty_slug)
            queryset = queryset.filter(category=category)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["categories"] = Category.objects.all()
        context["category"] = None
        context["is_manager"] = self.request.user.groups.filter(
            name="Менеджеры"
        ).exists()
        if "category_slug" in self.kwargs:
            context["category"] = get_object_or_404(
                Category, slug=self.kwargs["category_slug"]
            )
        return context


class ProductDetailView(DetailView):
    model = Product
    template_name = "shop/product/product_detail.html"
    context_object_name = "product"

    def get_queryset(self):
        return Product.objects.filter(slug=self.kwargs["slug"])


class OrderCreateView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        cart = get_object_or_404(Cart, user=self.request.user)
        if not cart.cart_item.exists():
            return redirect("product_list")

        form = OrderForm
        return render(request, "order/order_create.html", {"form": form, "cart": cart})

    def post(self, request, *args, **kwargs):
        cart = get_object_or_404(Cart, user=self.request.user)
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.user = request.user
            order.total_price = cart.get_total_price()
            order.save()

            for item in cart.cart_item.all():
                item.product.quantity = item.product.quantity - item.quantity
                item.product.save()

                OrderItem.objects.create(
                    order=order, product=item.product, quantity=item.quantity
                )

            cart.cart_item.all().delete()

            return redirect("payment", order_id=order.id)
        return redirect(
            request, "order/order_create.html", {"form": form, "cart": cart}
        )


class OrderConfirmationView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = "order/order_cofirmation.html"
    context_object_name = "order"

    def get_object(self):
        return get_object_or_404(
            Order, id=self.kwargs["order_id"], user=self.request.user
        )


class AddAlertView(View):
    def post(self, request, *args, **kwargs):
        product = get_object_or_404(Product, slug=self.kwargs["slug"])
        АvailabilityAlert.objects.get_or_create(user=request.user, product=product)
        return redirect("product_list")


class PaymentView(LoginRequiredMixin, FormView):
    template_name = "payments/payment_form.html"
    form_class = PaymentForm
    success_url = reverse_lazy("payment")

    payment_system: PaymentSystem = FakePaymentSystem()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)

        order_id = self.kwargs.get("order_id")
        order = get_object_or_404(Order, id=order_id, user=self.request.user)

        context["order"] = order
        context["total_price"] = order.total_price

        return context

    def form_valid(self, form):
        card_number = form.cleaned_data["card_number"]
        cvc = form.cleaned_data["cvc"]
        expired_date = form.cleaned_data["expired_date"]

        order_id = self.kwargs.get("order_id")
        order = get_object_or_404(Order, id=order_id, user=self.request.user)
        total_price = order.total_price

        result = self.payment_system.create_payment(
            total_price, card_number=card_number, cvc=cvc, expired_date=expired_date
        )

        if result["status"] == "success":
            order.payment_status = True
            order.save()
            return redirect("order_confirmation", order_id=order.id)

        context = self.get_context_data(result=result)
        return self.render_to_response(context)


class OrderListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = "order/users_orders.html"
    context_object_name = "orders"
    ordering = ["-created_at"]
    paginate_by = 5

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)
