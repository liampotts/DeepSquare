from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import GameViewSet, AIOptionsView

router = DefaultRouter()
router.register(r'games', GameViewSet)

urlpatterns = [
    path('ai/options/', AIOptionsView.as_view(), name='ai-options'),
    path('', include(router.urls)),
]
