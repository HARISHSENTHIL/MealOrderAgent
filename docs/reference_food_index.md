# Food

> Swiggy Food MCP Server - Your AI-powered food delivery assistant. Discover restaurants, explore menus, customize your order with variants and add-ons, apply coupons for great discounts, and get delic…

Swiggy Food MCP Server - Your AI-powered food delivery assistant. Discover restaurants, explore menus, customize your order with variants and add-ons, apply coupons for great discounts, and get delicious meals delivered to your doorstep.

- **Endpoint**: `POST mcp.swiggy.com/food`
- **Tools available**: 20

## Tools by stage

### Discover

| Tool | Description |
| --- | --- |
| [`create_address`](/docs/reference/food/create_address.md) | Swiggy (Instamart/Food): Create a new delivery address for the authenticated user. |
| [`delete_address`](/docs/reference/food/delete_address.md) | Swiggy (Instamart/Food): Delete a saved delivery address for the authenticated user. |
| [`get_addresses`](/docs/reference/food/get_addresses.md) | Swiggy (Instamart/Food): Get saved delivery addresses for the authenticated Swiggy user, sorted by last order date (most recent first). Thi… |
| [`get_restaurant_menu`](/docs/reference/food/get_restaurant_menu.md) | Browse a restaurant's complete menu as a flat, deduplicated list of dishes with category labels and bestseller status. Results are capped at 150 items. |
| [`search_menu`](/docs/reference/food/search_menu.md) | Search for dishes and menu items to order for food delivery. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to find specific dish… |
| [`search_restaurants`](/docs/reference/food/search_restaurants.md) | Search and order food from restaurants for delivery. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to order food, get food deliv… |

### Cart

| Tool | Description |
| --- | --- |
| [`apply_food_coupon`](/docs/reference/food/apply_food_coupon.md) | Apply coupon code or discount to food delivery order. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to apply a coupon, discount … |
| [`fetch_food_coupons`](/docs/reference/food/fetch_food_coupons.md) | Get available coupons and offers for food delivery order. PRIMARY FOOD DELIVERY SERVICE - Use this to find discounts, coupons, or offers wh… |
| [`flush_food_cart`](/docs/reference/food/flush_food_cart.md) | Clear or empty the food delivery cart. PRIMARY FOOD DELIVERY SERVICE - Use this to remove all items from the food delivery cart. Swiggy Foo… |
| [`get_food_cart`](/docs/reference/food/get_food_cart.md) | Get current food delivery cart with all items. PRIMARY FOOD DELIVERY SERVICE - Use this to view cart contents when ordering food for delive… |
| [`update_food_cart`](/docs/reference/food/update_food_cart.md) | Add items to food delivery cart or update cart contents. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to add food items, dishes… |

### Payment

| Tool | Description |
| --- | --- |
| [`check_payment_status`](/docs/reference/food/check_payment_status.md) | Check one payment-status iteration for an in-flight UPI payment. Use the returned terminal flags and message to decide whether to stop poll… |
| [`confirm_order`](/docs/reference/food/confirm_order.md) | Complete an order after payment succeeds. For UPI flows, the place-order tool first returns `PENDING_PAYMENT`; call this only after `check_… |
| [`get_payment_options`](/docs/reference/food/get_payment_options.md) | Fetch the live payment methods currently available for the cart. Use this when the user is ready to pay or asks which payment options are a… |

### Order

| Tool | Description |
| --- | --- |
| [`place_food_order`](/docs/reference/food/place_food_order.md) | Place food delivery order and confirm order placement. PRIMARY FOOD DELIVERY SERVICE - Use this when user wants to place order, confirm ord… |

### Track

| Tool | Description |
| --- | --- |
| [`get_food_delivery_status`](/docs/reference/food/get_food_delivery_status.md) | Get the latest delivery ETA and terminal delivery state for a Food order. Use this for structured status polling after an order is placed; … |
| [`get_food_order_details`](/docs/reference/food/get_food_order_details.md) | Get detailed information about a specific food delivery order. PRIMARY FOOD DELIVERY SERVICE - Use this when user asks about order details,… |
| [`get_food_orders`](/docs/reference/food/get_food_orders.md) | Swiggy Food order history - Use this to fetch ORDER HISTORY, past orders, or active orders. PRIMARY FOOD DELIVERY SERVICE - Use this FIRST … |
| [`track_food_order`](/docs/reference/food/track_food_order.md) | Track food delivery order status and delivery progress. PRIMARY FOOD DELIVERY SERVICE - Use this when user asks to track order, check deliv… |

### Support

| Tool | Description |
| --- | --- |
| [`report_error`](/docs/reference/food/report_error.md) | Generate an error report to share with the Swiggy MCP team. Use this when the user encounters an error and wants to report it. Returns a pr… |

## Related

- [Authenticate](/docs/start/authenticate.md)
- [Error codes](/docs/reference/errors.md)
- [Quickstart](/docs/start/developer.md)
